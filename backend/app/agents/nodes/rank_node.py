import math
from datetime import datetime

from app.agents.state import AgentState
from app.services.embeddings import embed_texts, similarity
from app.config import settings

CURRENT_YEAR = datetime.now().year
PRE_FILTER_N = 20
MMR_LAMBDA = 0.85


def _citation_score(citations) -> float:
    c = citations or 0
    return math.log(1 + c) / math.log(1 + 100_000)


def _recency_score(published: str) -> float:
    try:
        year = int(str(published)[:4])
    except (ValueError, TypeError):
        return 0.3
    age = max(CURRENT_YEAR - year, 0)
    return max(0.0, 1 - age / 15)


def _infer_paper_type(title: str, citations: int, published: str) -> str:
    t = title.lower()
    if any(k in t for k in ("survey", "review", "overview")):
        return "survey"
    if any(k in t for k in ("benchmark", "evaluation", "comparison")):
        return "evaluation"
    if any(k in t for k in ("efficient", "accelerat", "compress", "optimiz")):
        return "optimization"
    try:
        year = int(str(published)[:4])
        if (citations or 0) > 3000 and (CURRENT_YEAR - year) > 3:
            return "foundational"
    except (ValueError, TypeError):
        pass
    return "application"


def _weighted_score(paper: dict) -> float:
    relevance = paper.get("embedding_score", 0)
    citation = _citation_score(paper.get("citation_count", 0))
    recency = _recency_score(paper.get("published", ""))
    return 0.70 * relevance + 0.05 * citation + 0.25 * recency


def _mmr_select(papers: list[dict], vecs_by_title: dict, k: int, lam: float = MMR_LAMBDA) -> list[dict]:
    selected, remaining = [], list(papers)
    while remaining and len(selected) < k:
        if not selected:
            best = max(remaining, key=lambda p: p["final_score"])
        else:
            def mmr(p):
                sim_to_selected = max(
                    similarity(vecs_by_title[p["title"]], vecs_by_title[s["title"]]) for s in selected
                )
                return lam * p["final_score"] - (1 - lam) * sim_to_selected
            best = max(remaining, key=mmr)
        selected.append(best)
        remaining.remove(best)
    return selected


def rank_node(state: AgentState) -> AgentState:
    papers = state["raw_search_results"]
    if not papers:
        return {**state, "ranked_papers": [], "needs_retry": True}

    terms = state.get("search_terms") or [state.get("refined_query") or state["query"]]
    term_vecs = embed_texts(terms)

    abstracts = [p.get("summary", "")[:500] or p["title"] for p in papers]
    abstract_vecs = embed_texts(abstracts)

    vecs_by_title = {}
    for p, vec in zip(papers, abstract_vecs):
        p["embedding_score"] = round(max(similarity(tv, vec) for tv in term_vecs), 3)
        vecs_by_title[p["title"]] = vec

    for p in papers:
        p["paper_type"] = _infer_paper_type(p["title"], p.get("citation_count", 0), p.get("published", ""))
        p["final_score"] = round(_weighted_score(p), 3)

    seen = set()
    deduped = []
    for p in sorted(papers, key=lambda p: p["final_score"], reverse=True):
        norm = p["title"].strip().lower()
        if norm in seen:
            continue
        seen.add(norm)
        deduped.append(p)

    prefiltered = deduped[:PRE_FILTER_N]

    MIN_FINAL_SCORE = 0.45
    prefiltered = [p for p in prefiltered if p["final_score"] >= MIN_FINAL_SCORE]

    top_k = _mmr_select(prefiltered, vecs_by_title, settings.TOP_K_PAPERS) if prefiltered else []

    max_score = max((p["final_score"] for p in top_k), default=0)
    needs_retry = (
        max_score < 0.25
        and state.get("search_attempts", 0) < state.get("max_search_attempts", 2)
    )

    return {**state, "ranked_papers": top_k, "needs_retry": needs_retry}

