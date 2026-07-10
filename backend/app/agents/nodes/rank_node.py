import math
from datetime import datetime

from app.agents.state import AgentState
from app.services.embeddings import embed_texts, similarity
from app.config import settings

CURRENT_YEAR = datetime.now().year
PRE_FILTER_N = 20
MMR_LAMBDA = 0.85
MIN_ABSTRACT_LENGTH = 50
MIN_TERM_MATCH_SCORE = 0.35
WEAK_MATCH_BUFFER = 0.05
FULL_QUERY_THRESHOLD = 0.4


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


def _penalize_domain(ds: float) -> float:
    if ds < 0.25:
        return 0.1
    if ds < 0.35:
        return ds * 0.3
    return ds


def _weighted_score(paper: dict) -> float:
    relevance = paper.get("embedding_score", 0)
    citation = _citation_score(paper.get("citation_count", 0))
    recency = _recency_score(paper.get("published", ""))
    domain = _penalize_domain(paper.get("domain_score", 1.0))
    return 0.40 * relevance + 0.05 * citation + 0.20 * recency + 0.35 * domain


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

    query_vec = embed_texts([state["query"]])[0]
    q_abstracts = [p.get("summary", "")[:500] or p["title"] for p in papers]
    q_abstract_vecs = embed_texts(q_abstracts)

    filtered = []
    for i, p in enumerate(papers):
        sim = similarity(query_vec, q_abstract_vecs[i])
        if sim >= FULL_QUERY_THRESHOLD:
            p["full_query_similarity"] = round(sim, 3)
            filtered.append(p)

    if not filtered:
        return {**state, "ranked_papers": [], "needs_retry": True}
    papers = filtered

    terms = state.get("search_terms") or [state.get("refined_query") or state["query"]]
    term_vecs = embed_texts(terms)

    domain_full = state.get("domain_full")
    if domain_full:
        domain_vec = embed_texts([domain_full])[0]

    valid_papers = [p for p in papers if _has_valid_abstract(p)]
    invalid_papers = [p for p in papers if not _has_valid_abstract(p)]

    vecs_by_title = {}
    if valid_papers:
        abstracts = [p["summary"][:500] for p in valid_papers]
        abstract_vecs = embed_texts(abstracts)
        for p, vec in zip(valid_papers, abstract_vecs):
            p["embedding_score"] = round(max(similarity(tv, vec) for tv in term_vecs), 3)
            if domain_full:
                p["domain_score"] = round(similarity(domain_vec, vec), 3)
            else:
                p["domain_score"] = 1.0
            vecs_by_title[p["title"]] = vec

    for p in invalid_papers:
        p["embedding_score"] = 0.0
        p["domain_score"] = 0.0
        p["_no_abstract"] = True

    all_papers = valid_papers + invalid_papers

    for p in all_papers:
        p["paper_type"] = _infer_paper_type(p["title"], p.get("citation_count", 0), p.get("published", ""))
        p["final_score"] = round(_weighted_score(p), 3)
        if p.get("_no_abstract"):
            p["final_score"] = min(p["final_score"], 0.2)
        if p.get("_source_term") and p["embedding_score"] < MIN_TERM_MATCH_SCORE:
            p["_weak_term_match"] = True
            p["final_score"] = min(p["final_score"], p["embedding_score"] + WEAK_MATCH_BUFFER)

    seen = set()
    deduped = []
    for p in sorted(all_papers, key=lambda p: p["final_score"], reverse=True):
        norm = p["title"].strip().lower()
        if norm in seen:
            continue
        seen.add(norm)
        deduped.append(p)

    MIN_FINAL_SCORE = 0.45
    prefiltered = [p for p in deduped if p["final_score"] >= MIN_FINAL_SCORE][:PRE_FILTER_N]

    top_k = _mmr_select(prefiltered, vecs_by_title, settings.TOP_K_PAPERS) if prefiltered else []

    max_score = max((p["final_score"] for p in top_k), default=0)
    rank_needs_retry = (
        max_score < 0.25
        and state.get("search_attempts", 0) < state.get("max_search_attempts", 2)
    )

    return {**state, "ranked_papers": top_k, "needs_retry": state.get("needs_retry", False) or rank_needs_retry}
