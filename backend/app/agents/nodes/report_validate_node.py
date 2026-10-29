import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.state import AgentState
from app.config import settings
from app.services.llm_client import get_llm
from app.utils.numbers import all_numbers, number_in_text, parse_number, sign_preserved

log = logging.getLogger("report_mode")
HEDGES = ("approximately", "approx", "about", "around", "estimated", "derived", "calculated", "computed", "~")
_REFS = re.compile(r"\[(?:paper_id=\d+|user data|derived:[^\]]*)\]")
_BANNED = ("as an ai", "i'd be happy", "i hope this helps", "great question", "let me explain",
           "per the source data", "source data", "literature-based evidence", "retrieved source")
RESULT_IDS = {"results", "findings", "statements", "summary", "implementation", "body"}

_REVIEW_PROMPT = """You review a draft report against its evidence. Report ONLY serious problems:
- sections that CONTRADICT each other, or a section that contradicts itself (severity "error")
- a comparison of figures measured at different units, or a conclusion the evidence cannot support (severity "error")
- claims not supported by the evidence list, or invented context the user never gave (severity "warning")
- heavy repetition between sections, missing limitations (severity "warning")
Do not comment on style or grammar. Do not judge arithmetic.
For every "error", list the section ids that must be rewritten to fix it.

USER REQUEST:
{q}

EVIDENCE:
{ev}

SECTIONS:
{sec}

Return JSON only:
{{"warnings":[{{"description":"...","severity":"error|warning","section_ids":["id"]}}]}}
Max 5 items. Use an empty list if there are none."""


def _issue(t, sev, desc, section_ids=None, hint=None):
    return {"type": t, "severity": sev, "description": desc,
            "section_ids": section_ids or [], "revision_hint": hint or desc}


def validate_report(sections, records, evidence_text="", query="", n_papers=None) -> list[dict]:
    if not sections:
        return [_issue("section_failed", "error", "No sections were generated.")]

    issues = []
    full = "\n".join(s["content"] for s in sections)
    user = [r for r in records if r["category"] == "user_provided"]
    derived = [r for r in records if r["category"] == "derived"]
    by_id = {r["id"]: r for r in records}
    data_ids = [s["module_id"] for s in sections if s.get("data_scope") == "all"]
    target = [i for i in data_ids if i in RESULT_IDS] or data_ids

    for s in sections:
        if s.get("failed") or not s["content"].strip():
            issues.append(_issue("section_failed", "error", f"Section '{s['title']}' was not generated.", [s["module_id"]]))

    if n_papers is not None:
        for s in sections:
            bad = [int(x) for x in re.findall(r"\[paper_id=(\d+)\]", s["content"]) if int(x) >= n_papers]
            if bad:
                issues.append(_issue("invalid_citation", "error",
                                     f"Section '{s['title']}' cites unknown paper id {bad[0]}.",
                                     [s["module_id"]], "Remove citations to ids not in ALLOWED SOURCES."))

    for r in user:
        if r.get("role") == "other":
            continue
        sev = "error" if r.get("role") in ("count", "percentage", "amount") else "warning"
        if not number_in_text(r["value"], full):
            issues.append(_issue("number_missing", sev,
                                 f"User value {r['value']} ({r.get('field_name')}) is missing from the report.", target))
        elif not sign_preserved(r["value"], full):
            issues.append(_issue("sign_lost", "error",
                                 f"Negative value {r['value']} ({r.get('field_name')}) lost its sign.", target))

    for r in user:
        if r.get("role") == "percentage" and r.get("denominator_ref") in by_id:
            den = parse_number(by_id[r["denominator_ref"]]["value"])
            pat = rf"{re.escape(r['value'])}\s*%\s+of\s+(?:the\s+|all\s+)?(?:total\s+)?(\d[\d,\.]*)"
            for m in re.finditer(pat, full):
                if parse_number(m.group(1)) != den:
                    issues.append(_issue("wrong_denominator", "error",
                                         f"{r['value']}% is stated against {m.group(1)} but its denominator is "
                                         f"{by_id[r['denominator_ref']]['value']}.", target))

    provided = {parse_number(r["value"]) for r in user} | {parse_number(r["value"]) for r in derived}
    for r in user:
        if r.get("role") == "percentage" and r.get("denominator_ref") in by_id:
            pct, den = parse_number(r["value"]), parse_number(by_id[r["denominator_ref"]]["value"])
            if pct is None or den is None:
                continue
            guess = int((pct * den / 100).to_integral_value())
            if guess in provided or guess <= 10:
                continue
            for m in re.finditer(rf"(?<![\d.,]){guess}(?![\d]|[.,]\d)", full):
                ctx = full[max(0, m.start() - 80): m.end() + 80].lower()
                if not any(h in ctx for h in HEDGES):
                    issues.append(_issue("invented_count", "error",
                                         f"{guess} looks derived from {r['value']}% of {den} but was not provided; "
                                         f"remove it or label it as approximate.", target))
                    break

    allowed = {parse_number(r["value"]) for r in user + derived} \
              | set(all_numbers(evidence_text)) | set(all_numbers(query))
    clean = _REFS.sub("", "\n".join(l for l in full.splitlines() if not l.lstrip().startswith("#")))
    stray = []
    for d in all_numbers(clean):
        is_int = d == d.to_integral_value()
        if d in allowed or (is_int and (0 <= d <= 10 or 1900 <= d <= 2100)):
            continue
        stray.append(format(d, "f"))
    if stray:
        issues.append(_issue("untraceable_numbers", "warning",
                             "Numbers with no source: " + ", ".join(sorted(set(stray))[:10])))

    low = full.lower()
    for b in _BANNED:
        if b in low:
            issues.append(_issue("boilerplate", "warning", f"Conversational phrase found: '{b}'."))

    if low.count("unit of analysis") > 1:
        offenders = [s["module_id"] for s in sections if "unit of analysis" in s["content"].lower()]
        issues.append(_issue(
            "boilerplate", "error",
            "'unit of analysis' appears more than once; state each unit once in the first section "
            "where the figure appears, and nowhere else.",
            offenders,
            "Delete every '(unit of analysis: ...)' parenthetical from this section."))

    basis = (evidence_text + " " + query).lower()
    for m in re.finditer(
        r"\b([A-Z][A-Za-z]+(?:\s+(?:of|and|for|the)?\s*[A-Z][A-Za-z]+){2,})\s*\(([A-Z]{3,})\)", full):
        phrase, acr = m.group(1), m.group(2)
        if phrase.lower() not in basis:
            sev = "error" if acr in query else "warning"
            offenders = [s["module_id"] for s in sections if phrase in s["content"]]
            issues.append(_issue("acronym_expansion", sev,
                f"'{phrase}' as the expansion of {acr} is not in the user's input or sources.",
                offenders,
                f"Do not expand {acr}; use it exactly as the user wrote it."))
                
    return issues


def _llm_review(state, sections) -> list[dict]:
    ev = "\n".join(
        f"- {i.get('content', '')[:160]}"
        for i in (state.get("evidence_ledger") or [])[:20]
        if i.get("category") != "gap"
    )
    sec = "\n\n".join(f"[{s['module_id']}] {s['title']}\n{s['content'][:1400]}" for s in sections[:8])
    try:
        raw = get_llm(temperature=0, task="fast").invoke_json_mode(
            [SystemMessage(content="You are a report reviewer. Return only JSON."),
             HumanMessage(content=_REVIEW_PROMPT.format(q=state.get("query", "")[:800], ev=ev or "(none)", sec=sec))],
            config={"timeout": 15},
        )
        items = raw.get("warnings", []) if isinstance(raw, dict) else []
    except Exception:
        log.exception("report llm review failed")
        return []

    valid = {s["module_id"] for s in sections}
    out = []
    for it in items[:5]:
        if not isinstance(it, dict):
            continue
        desc = str(it.get("description", "")).strip()
        if len(desc) < 12:
            continue
        sids = [x for x in (it.get("section_ids") or []) if x in valid]
        is_error = str(it.get("severity", "")).lower() == "error" and bool(sids)
        if is_error:
            out.append(_issue("contradiction", "error", desc[:300], sids,
                              desc[:300] + " Rewrite so this section agrees with the rest; state the point once."))
        else:
            out.append(_issue("editorial", "warning", desc[:300], sids))
    return out


def report_validate_node(state: AgentState) -> AgentState:
    sections = state.get("section_outputs") or []
    papers = state.get("ranked_papers") or []
    evidence = "  ".join((p.get("summary") or p.get("text") or " ") for p in papers[:8])

    disc = " ".join(d.get("description", "") for d in state.get("report_discrepancies") or [])
    issues = validate_report(sections, state.get("report_source_records") or [],
                             evidence + " " + disc, state.get("query", " "), len(papers))

    if sections and state.get("report_execution_path") in ("standard", "deep"):
        issues += _llm_review(state, sections)

    errors = [i for i in issues if i["severity"] == "error"]

    log.info("report_validate errors=%d rev=%s",
             len(errors), state.get("report_revision_count", 0))

    return {"report_validation_results": {"passed": not errors, "errors": errors}}


def route_after_report_validate(state: AgentState) -> str:
    res = state.get("report_validation_results") or {}
    if res.get("errors") and state.get("report_revision_count", 0) < settings.REPORT_MAX_REVISIONS:
        return "revise"
    return "finalize"