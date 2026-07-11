import math
from datetime import datetime

from app.agents.state import AgentState
from app.services.embeddings import embed_texts, similarity
from app.config import settings

CURRENT_YEAR = datetime.now().year
PRE_FILTER_N = 20
MMR_LAMBDA = 0.85
MIN_ABSTRACT_LENGTH = 50


def _has_valid_abstract(paper: dict) -> bool:
    return len(paper.get("summary", "").strip()) >= MIN_ABSTRACT_LENGTH


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
    if any(k in t for k in ("survey", "review", "overview", "systematic review", "meta-analysis")):
        return "survey"
    if any(k in t for k in ("benchmark", "evaluation", "comparison", "randomized controlled trial", "clinical trial")):
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
        return {**state, "ranked_papers": [], "needs_retry": True, "papers_below_threshold": 0}

    terms = state.get("search_terms") or [state.get("refined_query") or state["query"]]
    term_vecs = embed_texts(terms)

    valid_papers = [p for p in papers if _has_valid_abstract(p)]
    invalid_papers = [p for p in papers if not _has_valid_abstract(p)]

    vecs_by_title = {}
    if valid_papers:
        abstracts = [p["summary"][:500] for p in valid_papers]
        abstract_vecs = embed_texts(abstracts)
        for p, vec in zip(valid_papers, abstract_vecs):
            p["embedding_score"] = round(max(similarity(tv, vec) for tv in term_vecs), 3)
            vecs_by_title[p["title"]] = vec

    for p in invalid_papers:
        p["embedding_score"] = 0.0
        p["_no_abstract"] = True

    all_papers = valid_papers + invalid_papers
    for p in all_papers:
        p["paper_type"] = _infer_paper_type(p["title"], p.get("citation_count", 0), p.get("published", ""))
        p["final_score"] = round(_weighted_score(p), 3)
        if p.get("_no_abstract"):
            p["final_score"] = min(p["final_score"], 0.2)

    seen = set()
    deduped = []
    for p in sorted(all_papers, key=lambda p: p["final_score"], reverse=True):
        norm = p["title"].strip().lower()
        if norm in seen:
            continue
        seen.add(norm)
        deduped.append(p)

    prefiltered_before_threshold = deduped[:PRE_FILTER_N]
    prefiltered = [p for p in prefiltered_before_threshold if p["final_score"] >= settings.MIN_FINAL_SCORE]
    dropped_count = len(prefiltered_before_threshold) - len(prefiltered)

    target_k = min(len(prefiltered), settings.TOP_K_PAPERS_MAX)
    top_k = _mmr_select(prefiltered, vecs_by_title, target_k) if prefiltered else []

    needs_retry = (
        len(top_k) < settings.TOP_K_PAPERS_MIN
        and state.get("search_attempts", 0) < state.get("max_search_attempts", 2)
    )

    return {
        **state,
        "ranked_papers": top_k,
        "needs_retry": state.get("needs_retry", False) or needs_retry,
        "papers_below_threshold": dropped_count,
    }
