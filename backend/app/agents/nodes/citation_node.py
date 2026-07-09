from app.agents.state import AgentState


SOURCE_LABELS = {
    "arxiv": "arXiv",
    "openalex": "OpenAlex",
    "semantic_scholar": "Semantic Scholar",
}


def _format_apa(paper: dict) -> str:
    authors = paper.get("authors", [])
    author_str = ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "")
    year = paper.get("published", "n.d.")[:4]
    label = SOURCE_LABELS.get(paper.get("source", ""), "Web")
    return f"{author_str} ({year}). {paper['title']}. {label}. {paper['link']}"


def citation_node(state: AgentState) -> AgentState:
    citations = [_format_apa(p) for p in state["ranked_papers"]]
    return {**state, "citations": citations}
