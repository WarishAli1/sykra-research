import logging
import re
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.nodes.summarize_node import (
    _block_for_ids, _clean_content, _dedupe_sections, _estimate_tokens, _evidence_mode_instruction,
    _fast_summaries, _ground_sections, _reclassify_evidence_types, _request_token_limit, _strip_leading_title,
)
from app.agents.report_text import report_extra_text
from app.agents.state import AgentState
from app.config import settings
from app.services.llm_client import get_llm
from app.services.reference_builder import extract_paper_ids
from app.services.sse import bridge_push

log = logging.getLogger("report_mode")
SUMMARY_IDS = {"abstract", "executive_summary", "conclusion", "conclusions"}


DISCREPANCY_IDS = {"results", "findings", "body", "recommendations", "limitations"}


_ORPHAN_RE = re.compile(
    r"^(\s*(?:[-*]\s+|\d+\.\s+)?)(?:Consequently|Therefore|Thus|Hence|However|Moreover|Furthermore|Additionally),?\s+(\S)",
    re.M,
)


_EXP_RE = re.compile(r"\b([A-Z][A-Za-z]+(?:\s+(?:of|and|for|the)?\s*[A-Z][A-Za-z]+){2,})\s*\(([A-Z]{3,})\)")

def _strip_invented_expansions(text: str, basis: str) -> str:
    return _EXP_RE.sub(lambda m: m.group(0) if m.group(1).lower() in basis else m.group(2), text or "")

    
_EV_RE = re.compile(r"\[ev_[a-z]+_(\d+)\]\s*", re.I)


def _fix_ev_citations(text: str, ledger: list, n_papers: int) -> str:
    by_id = {str(i.get("id")): i.get("paper_id") for i in ledger if isinstance(i.get("paper_id"), int)}

    def repl(m):
        pid = by_id.get(m.group(0).strip()[1:-1], int(m.group(1)))
        return f"[paper_id={pid}]" if 0 <= pid < n_papers else ""

    return _EV_RE.sub(repl, text or "")


def _strip_orphan_connectives(text: str) -> str:
    """After grounding deletes a sentence, a leading connective can lose its antecedent.
    A connective at the start of a line (paragraph or bullet) has no antecedent in that line."""
    return _ORPHAN_RE.sub(lambda m: m.group(1) + m.group(2).upper(), text or "")


_SYSTEM = """You write ONE section of a professional report. Markdown only. No heading, no <think>.
DATA INTEGRITY (highest priority):
- SOURCE DATA values are authoritative. Copy every number exactly as written; never round, convert,
  normalise, drop a sign, or change units.
- State the unit of analysis and denominator ONCE, where a figure is first introduced. Never write a
  "(unit of analysis: ...)" parenthetical. Never show multiplication such as "0.37 x 328 = ...".
  Counts are whole numbers.
- Use a CALCULATED count only if it is listed under SOURCE DATA, and say it is approximate.
- Never invent: methods, objectives, institutions, herd or farm descriptions, sample sizes, species
  splits, dates. If the brief does not state a study objective, do not write one.
- Never expand an acronym that the user did not expand. Use it exactly as given.
- If KNOWN DISCREPANCIES lists an inconsistency between the user's figures, report that inconsistency
  plainly and ask the author to confirm. Never assert the inconsistent relationship as fact
  (e.g. never write "four teats per animal" if the figures do not give four per animal).
- Say what was NOT provided instead of filling the gap.
COMPARING WITH LITERATURE:
- Compare the user's figure only with a cited figure at the SAME unit (quarter vs quarter, animal vs
  animal). If the units differ, say so once and do not compare. Never describe the user's figure as
  "between", "aligned with", "consistent with", "higher" or "lower" unless the units match.
- Name the differences (species, country, method, test threshold) when comparing. Draw no conclusion
  about the user's result being validated or confirmed by another study. No statistical claim
  without a test or interval.
- A screening test (e.g. CMT) is not a diagnosis of infection. Do not claim infection from it.
CITATIONS:
- Never write evidence ids such as [ev_paper_1]. The only citation form is [paper_id=N].
- Cite literature as [paper_id=N], one id per bracket, only ids under ALLOWED SOURCES, only for what
  that excerpt states. Never cite anything for the user's own data. Never attribute to a cited study
  a measure (sensitivity, specificity, prevalence) its excerpt does not mention.
- Do not write uncited background (reagent chemistry, mechanisms, thresholds). If it needs a
  citation and none supports it, leave it out.
RECOMMENDATIONS (only if this section is recommendations or next steps):
- Each recommendation must follow directly from a stated finding or a stated data gap. No generic
  husbandry, nutrition or training advice. Frame them as follow-up steps for the report's author
  (what to collect, confirm or retest), unless the user asked for farmer-facing advice.
- Do not invent schedules or frequencies.
STYLE: objective, precise. Say each fact in full once; later sections refer to it briefly instead of
restating it. Write every sentence so it stands alone: do not begin a sentence with "Consequently",
"Therefore", "Thus", "Hence" or "However" unless its cause is in the same paragraph. Never mention
"source data", "the ledger", "retrieved sources" or "literature-based evidence". No filler, no AI
self-reference.
- Never compute expected totals (e.g. "77 x 4") or per-animal averages yourself; only restate a discrepancy exactly as listed.
- Never describe the section itself ("The purpose of this introduction is..."). Start with content.
- Never state that figures are consistent, aligned or as expected unless KNOWN DISCREPANCIES is "(none)" and SOURCE DATA shows the arithmetic.
Math: inline $x$; display $$ on its own lines with blank lines around. Currency: write "USD 48", never "$48"."""


def _source_block(records, scope):
    if scope == "none":
        return "(not applicable to this section; do not introduce figures here)"
    rows = [r for r in records if r["category"] in ("user_provided", "derived")]
    if not rows:
        return "(none extracted. Use only figures stated in the USER BRIEF, copied exactly; do not compute counts from percentages.)"
    out = []
    for r in rows:
        tag = "USER DATA" if r["category"] == "user_provided" else "CALCULATED"
        unit = f" {r['unit']}" if r.get("unit") else ""
        uoa = f" [unit of analysis: {r['unit_of_analysis']}]" if r.get("unit_of_analysis") else ""
        calc = f" (calculation: {r['transformation']})" if r.get("transformation") else ""
        out.append(f"- [{tag}] {r.get('field_name') or 'value'}: {r['value']}{unit}{uoa}{calc}")
    return "\n".join(out)


def _discrepancy_block(ds):
    return "\n".join(f"- {d['description']}" for d in ds[:5]) or "(none)"


def _digest(done, chars):
    if not done or chars <= 0:
        return "(none)"
    return "\n".join(f"- {s['title']}: {s['content'][:chars].replace(chr(10), ' ')}" for s in done if s["content"])


def _section_contract(state: AgentState, section_id: str) -> dict:
    for c in state.get("report_section_contracts") or []:
        if c.get("section_id") == section_id:
            return c
    return {}


def _evidence_ledger_block(state: AgentState, limit: int = 18) -> str:
    ledger = state.get("evidence_ledger") or []
    if not ledger:
        return "(no evidence ledger available)"

    lines = []
    for ev in ledger[:limit]:
        if ev.get("category") == "gap":
            continue
        pid = ev.get("paper_id")
        tag = f"cite as [paper_id={pid}]" if isinstance(pid, int) else str(ev.get("category"))
        lines.append(f"- ({tag}) {str(ev.get('content', ''))[:180]}")

    gaps = state.get("evidence_gaps") or []
    if gaps:
        lines.append("KNOWN EVIDENCE GAPS:")
        lines.extend(f"- {g}" for g in gaps[:5])

    return "\n".join(lines)


def _build_prompt(section, state, done, evidence_block, ids, digest_chars, fix, previous):
    contract = _section_contract(state, section.get("section_id"))

    prohibited = contract.get("prohibited") or []

    prohibited_block = "\n".join(f"- {p}" for p in prohibited) if prohibited else "- none"

    disc_text = _discrepancy_block(state.get('report_discrepancies') or [])
    if section.get("section_id") in DISCREPANCY_IDS or disc_text == "(none)":
        disc = disc_text
    else:
        disc = ("(state once, in one short sentence, exactly as listed below; no arithmetic; "
                "never say the figures are consistent)\n" + disc_text)

    p = f"""REPORT TYPE: {state.get('report_type', 'general')}
REPORT TITLE: {state.get('report_title', '')}
AUDIENCE: {state.get('report_audience', 'academic')}
{_evidence_mode_instruction(state.get('evidence_mode', 'literature'))}

SECTION: {section['title']}
PURPOSE: {section['purpose']}
TARGET LENGTH: about {section['target_words']} words

SECTION CONTRACT:
- evidence_required: {contract.get('evidence_required', False)}
- required_citations: {contract.get('required_citations', False)}
- data_scope: {contract.get('data_scope', 'all')}
- prohibited:
{prohibited_block}

USER BRIEF:
{(state.get('query') or '')[:1500]}

SOURCE DATA:
{_source_block(state.get('report_source_records') or [], section.get('data_scope', 'all'))}

EVIDENCE LEDGER:
{_evidence_ledger_block(state)}

KNOWN DISCREPANCIES:
{disc}

ALLOWED SOURCES: {', '.join(map(str, ids)) or 'none'}
{evidence_block}

ALREADY WRITTEN:
{_digest(done, digest_chars)}

Write only this section.
Use only the evidence ledger and source data above.
If evidence is missing, say it is not provided.
Never invent facts, numbers, citations, or conclusions."""

    if fix:
        p += f"""

YOUR PREVIOUS DRAFT:
{previous}

FIX ONLY THESE PROBLEMS:
{fix}"""

    return p


def write_section(section, state, papers, summaries, done, fix=None, previous=None):
    limit = _request_token_limit()
    max_out = min(max(400, section["target_words"] * 3), int(limit * 0.30))
    want = settings.REPORT_EVIDENCE_PAPERS if section.get("evidence_required") else 0
    ids = list(range(min(len(papers), want)))

    for digest_chars in (300, 120, 0):          
        base = _build_prompt(section, state, done, "", ids, digest_chars, fix, previous)
        room = int(limit * 0.85) - max_out - _estimate_tokens(base)
        if room > 0 or digest_chars == 0:
            break
    avail = max(0, room) * 4
    while ids and avail // len(ids) < 300:
        ids.pop()
    chars = min(900, avail // len(ids)) if ids else 0
    block = _block_for_ids(papers, summaries, ids, chars) if ids else ""
    prompt = _build_prompt(section, state, done, block, ids, digest_chars, fix, previous)

    content, failed = "", True
    for _ in range(2):
        try:
            raw = get_llm(temperature=0, task="strong").invoke(
                [SystemMessage(content=_SYSTEM), HumanMessage(content=prompt)],
                max_tokens=max_out, config={"timeout": settings.REPORT_SECTION_TIMEOUT_DEEP})
            content = _strip_leading_title(_clean_content(raw.content), section["title"])
            if len(content.split()) >= 15 or section["target_words"] <= 30:
                failed = False
                break
        except Exception:
            log.exception("report section failed id=%s", section["section_id"])
    return {
        "module_id": section["section_id"], "title": section["title"], "content": content,
        "failed": failed, "data_scope": section.get("data_scope", "all"),
        "cited_paper_ids": extract_paper_ids(content), "seen_ids": [str(i) for i in ids],
        "evidence_status": "strong" if extract_paper_ids(content) else "mixed", "confidence": "medium",
    }


def postprocess(sections, state, papers, only_ids=None):
    """Dedupe, then your existing grounding pass. User/derived values are passed as extra_text
    so ground_text does not strip them as 'unsupported'."""
    ledger = state.get("evidence_ledger") or []
    for s in sections:
        if not s.get("failed"):
            s["content"] = _fix_ev_citations(s["content"], ledger, len(papers))
    sections = _dedupe_sections(sections)
    seen = {i for s in sections for i in s.get("seen_ids", [])}
    aug = {**state, "query": report_extra_text(state), "_seen_paper_ids": seen}
    targets = [s for s in sections if not s.get("failed") and (only_ids is None or s["module_id"] in only_ids)]
    _ground_sections(targets, papers, aug)
    basis = (state.get("query") or "").lower()
    for s in targets:
        s["content"] = _strip_orphan_connectives(_strip_invented_expansions(s["content"], basis))
    return sections


def report_writer_node(state: AgentState) -> AgentState:
    papers = state.get("ranked_papers") or []
    summaries = _reclassify_evidence_types(papers, _fast_summaries(papers, state), state)

    plan = [s for s in (state.get("report_section_plan") or [])
            if s["section_id"] not in ("title", "references")]
    if not plan:
        raise RuntimeError("report plan is empty")

    body = [s for s in plan if s["section_id"] not in SUMMARY_IDS]
    tail = [s for s in plan if s["section_id"] in SUMMARY_IDS]
    ordered = body + tail

    rid = state.get("_request_id")
    live = bool(rid and state.get("_streaming_enabled"))
    cancel = state.get("_cancel_check")

    done = []
    for n, s in enumerate(ordered, 1):
        if cancel and cancel():
            break
        res = write_section(s, state, papers, summaries, done)
        done.append(res)
        if live:
            bridge_push(rid, ("progress", "report_writer",
                            {"detail": f"Written {n} of {len(ordered)}: {s['title']}"}))
            bridge_push(rid, ("report_section_draft", res["module_id"], res["title"], res["content"]))

    order = {s["section_id"]: i for i, s in enumerate(plan)}
    done.sort(key=lambda s: order[s["module_id"]])
    done = postprocess(done, state, papers)
    return {"section_outputs": done, "summaries": summaries}


_RESULT_IDS = {"results", "findings", "statements", "summary", "implementation", "body"}


def report_revise_node(state: AgentState) -> AgentState:
    errors = (state.get("report_validation_results") or {}).get("errors") or []
    sections = list(state.get("section_outputs") or [])
    plan = {s["section_id"]: s for s in (state.get("report_section_plan") or [])}
    papers = state.get("ranked_papers") or []
    summaries = state.get("summaries") or {}
    count = (state.get("report_revision_count") or 0) + 1

    if not errors or not sections:
        return {"section_outputs": sections, "report_revision_count": count}

    fixes: dict[str, list[str]] = {}
    for e in errors:
        hint = e.get("revision_hint") or e.get("description")
        if hint:
            for sid in e.get("section_ids") or []:
                fixes.setdefault(sid, []).append(hint)

    target_ids = set(fixes)
    if not target_ids:
        target_ids = {s["module_id"] for s in sections
                      if s.get("failed") or not (s.get("content") or "").strip()}
    if not target_ids:
        target_ids = {s["module_id"] for s in sections if s.get("module_id") in _RESULT_IDS}
    if not target_ids:
        target_ids = {sections[0]["module_id"]}

    changed = set()
    for i, s in enumerate(sections):
        sid = s["module_id"]
        if sid not in target_ids or sid not in plan:
            continue
        others = [x for j, x in enumerate(sections) if j != i]
        section_fixes = fixes.get(sid) or [e.get("description", "") for e in errors]
        fix_text = "\n".join(f"- {m}" for m in section_fixes if m)
        sections[i] = write_section(plan[sid], state, papers, summaries, others,
                                    fix=fix_text, previous=s["content"])
        changed.add(sid)

    sections = postprocess(sections, state, papers, only_ids=changed)
    return {"section_outputs": sections, "report_revision_count": count}