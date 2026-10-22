import re

from app.agents.state import AgentState
from app.config import settings
from app.services.citation_grounding import ground_text
from app.services.reference_builder import (
    CitationNumberer,
    paper_id_to_ref_id_map,
)
from app.services.citation_formatter import format_apa


def _method_note(state, n_cited):
    mode = state.get("response_mode", "normal")
    n_rank = len(state.get("ranked_papers") or [])
    if mode == "normal":
        return (f"Direct mode: quick answer from {n_rank} retrieved sources, {n_cited} cited. "
                "Not a systematic review; claims were not independently audited.")
    n_q = len((state.get("retrieval_plan") or {}).get("intents") or [])
    n_found = len(state.get("raw_search_results") or [])
    ver = state.get("verification_status", "not_run")
    return (f"Researched mode: {n_q} search intents, {n_found} candidates retrieved, {n_rank} ranked, "
            f"{n_cited} cited. Citations were automatically checked against source abstracts "
            f"(claim audit: {ver}). This is targeted retrieval and evidence synthesis, not a systematic "
            "review (no registered protocol, exhaustive search or formal risk-of-bias assessment).")


def citation_node(state: AgentState) -> AgentState:
    papers = state.get("ranked_papers", [])
    final_answer = state.get("final_answer", "") or ""

    if final_answer and papers:
        texts_by_id = {
            str(i): f"{p.get('title', '')}. {p.get('summary') or p.get('text') or ''}"
            for i, p in enumerate(papers)
        }
        final_answer, drops = ground_text(
            final_answer,
            texts_by_id,
            None,
            numeric_check=getattr(settings, "GROUNDING_NUMERIC_CHECK_ENABLED", True),
        )
        if drops:
            print(f"[ground:final] dropped/adjusted {len(drops)} claim(s) after revision")
            for d in drops:
                print(f"[ground:final]   - {d['reason']}: {d['sentence']}")

    cited = []
    for pid in dict.fromkeys(
        re.findall(r"\[paper_id=(\d+)\]", final_answer)
    ):
        idx = int(pid)
        if 0 <= idx < len(papers):
            cited.append(papers[idx])
    citations = [format_apa(p) for p in cited]

    references = state.get("references", []) or []
    if final_answer:
        id_map = paper_id_to_ref_id_map(papers, references)
        numberer = CitationNumberer(id_map)
        final_answer = numberer.rewrite(final_answer)
        references = numberer.renumber_references(references)

    print("[cite-debug] final ref ids:", [r["id"] for r in references])

    return {
        "method_note": _method_note(state, len(references)),
        "citations": citations,
        "final_answer": final_answer,
        "references": references,
    }