from app.agents.state import AgentState
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

    return {
        "citations": citations,
    }