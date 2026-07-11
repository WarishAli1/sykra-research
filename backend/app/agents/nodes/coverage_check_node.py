from app.agents.state import AgentState
from app.services.embeddings import embed_texts, similarity
from app.config import settings


def coverage_check_node(state: AgentState) -> AgentState:
    terms = state.get("search_terms") or [state["query"]]
    papers = state["ranked_papers"]

    if not papers:
        return {**state, "term_coverage": {t: False for t in terms}}

    term_vecs = embed_texts(terms)
    paper_texts = [p.get("text", p.get("summary", ""))[:1000] for p in papers]
    paper_vecs = embed_texts(paper_texts)

    coverage = {}
    for term, term_vec in zip(terms, term_vecs):
        best_sim = max(similarity(term_vec, pv) for pv in paper_vecs)
        coverage[term] = bool(best_sim >= settings.COVERAGE_THRESHOLD)

    return {**state, "term_coverage": coverage}
