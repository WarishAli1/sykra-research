from app.agents.state import AgentState
from app.services.reference_builder import (
    build_references,
    paper_id_to_ref_id_map,
    rewrite_inline_citations,
)
from app.services.citation_formatter import format_apa


def citation_node(state: AgentState) -> AgentState:
    papers = state.get("ranked_papers", [])
    cited_ids = state.get("cited_paper_ids", [])

    selected_papers = []

    if cited_ids:
        for pid in cited_ids:
            try:
                idx = int(pid)
            except (TypeError, ValueError):
                continue

            if 0 <= idx < len(papers):
                selected_papers.append(papers[idx])

    if not selected_papers:
        selected_papers = papers

    citations = [format_apa(p) for p in selected_papers]

    final_answer = state.get("final_answer", "")
    references = state.get("references", []) or build_references(papers)
    if final_answer:
        id_map = paper_id_to_ref_id_map(papers, references)
        final_answer = rewrite_inline_citations(final_answer, id_map)

    return {
        "citations": citations,
        "final_answer": final_answer,
    }