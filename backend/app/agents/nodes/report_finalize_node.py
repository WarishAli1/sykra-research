import re

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.nodes.summarize_node import (
    _OrderedSectionEmitter, _collect_cited_paper_ids, _compute_dynamic_confidence,
    _sanitize_preserving_math, _select_references,
)
from app.agents.state import AgentState
from app.config import settings
from app.services.llm_client import get_llm
from app.services.reference_builder import CitationNumberer, build_references, paper_id_to_ref_id_map
import logging
from app.agents.report_text import is_auto_title


log = logging.getLogger("report_mode")
_THINK_RE = re.compile(r"<think>.*?</think>", re.S | re.I)
_FAILED = "> **This section could not be generated. Please regenerate the report.**"

_PID_RE = re.compile(r"\[paper_id=(\d+)\]")
def _topic_title(state) -> str:
    topic = str((state.get("query_understanding") or {}).get("main_topic") or "").strip()
    return (topic[:1].upper() + topic[1:])[:110] if topic else "Report"


def _final_title(state: AgentState, rendered) -> str:
    if state.get("report_title_user_supplied"):
        return (state.get("report_title") or "Report").strip()
    query = state.get("query") or ""
    digest = "\n".join(f"{h}: {t[:200]}" for _, h, t in rendered[:4])
    try:
        raw = get_llm(temperature=0, task="fast").invoke(
            [SystemMessage(content=(
                "You write titles for professional reports. Return ONLY the title: 6-16 words, "
                "title case, no quotes, no trailing period. Name what was measured, in what "
                "population, and where, if the report states it. Never copy the user's request. "
                "Never claim anything the report does not state.")),
             HumanMessage(content=f"User request (context only):\n{query[:500]}\n\nReport opening:\n{digest}")],
            max_tokens=200, config={"timeout": 10})
        text = _THINK_RE.sub("", raw.content or "").strip()
        title = re.sub(r'^[#"\s]+|["\s.]+$', "", text.splitlines()[0]) if text else ""
        if 12 <= len(title) <= 140 and not is_auto_title(title, query):
            return title
        log.warning("title rejected: %r", title)
    except Exception:
        log.exception("title generation failed")
    return _topic_title(state)


def report_finalize_node(state: AgentState) -> AgentState:
    sections = state.get("section_outputs") or []

    papers = state.get("ranked_papers") or []
    summaries = state.get("summaries") or {}
    plan = state.get("report_plan") or {}

    rendered = []
    for s in sections:
        text = _FAILED if (s.get("failed") or not s["content"].strip()) else s["content"].strip()
        rendered.append((s["module_id"], s["title"], re.sub(r"[ \t]+\n", "\n", text)))

    title = _final_title(state, rendered)
    head = f"# {title}\n"
    answer = "\n".join([head] + [f"## {h}\n\n{t}\n" for _, h, t in rendered]).strip()
    references = build_references(papers)
    if state.get("evidence_mode") == "uploaded":
        references = [r for r in references if r.get("source") == "user_upload"]
    id_map = paper_id_to_ref_id_map(papers, references)
    cited = _collect_cited_paper_ids(sections, papers)
    cited_ref_ids = {id_map[p] for p in cited if p in id_map}
    selected = _select_references(references, cited_ref_ids, plan, papers, summaries)
    min_refs = int(getattr(settings, "REPORT_MIN_REFERENCES", 7))
    if len(selected) < min_refs:
        key = lambda r: r.get("link") or r.get("title")
        have = {key(r) for r in selected}
        nxt = max([r.get("id", 0) for r in selected] or [0]) + 1
        for r in references:
            if len(selected) >= min_refs:
                break
            if key(r) not in have:
                selected.append({**r, "id": nxt}); have.add(key(r)); nxt += 1

    request_id = state.get("_request_id", "")
    if request_id and state.get("_streaming_enabled"):
        ids = ["report_head"] + [m for m, _, _ in rendered] + ["report_foot"]
        em = _OrderedSectionEmitter(ids, request_id, state.get("_cancel_check"), CitationNumberer(id_map))
        em.submit("report_head", head)
        for mid, h, t in rendered:
            em.submit(mid, f"## {h}\n\n{_sanitize_preserving_math(t)}\n")
        em.flush_remaining()

    return {
        "final_answer": answer, "references": selected, "cited_paper_ids": cited,
        "summaries": summaries, "section_outputs": sections,
        "module_evidence_map": {}, "evidence_matrix": {}, "coverage_gaps": [], "domain_caveat": None,
        "dynamic_confidence": _compute_dynamic_confidence(state, papers, summaries, sections, {}, plan),
    }