import math
from datetime import datetime
from app.agents.state import AgentState
from app.services.embeddings import embed_texts, similarity
from app.services.paper_search import fetch_openalex_citation_graph
from app.config import settings

CURRENT_YEAR = datetime.now().year
PRE_FILTER_N = 30
MMR_LAMBDA = 0.85
MIN_ABSTRACT_LENGTH = 50
_RELAXATION_TIERS = [1.0, 0.7, 0.45, 0.25]
_ABSOLUTE_FLOOR = 0.08

def _has_valid_abstract(paper: dict) -> bool:
    return len(paper.get("summary", "").strip()) >= MIN_ABSTRACT_LENGTH

def _citation_score(citations) -> float:
    c = citations or 0
    return math.log(1 + c) / math.log(1 + 100_000)

def _recency_score(published: str) -> float:
    try: year = int(str(published)[:4])
    except (ValueError, TypeError): return 0.3
    age = max(CURRENT_YEAR - year, 0)
    return max(0.0, 1 - age / 15)

def _infer_paper_type(title: str, citations: int, published: str) -> str:
    t = title.lower()
    if any(k in t for k in ("survey", "review", "overview", "systematic review", "meta-analysis")): return "survey"
    if any(k in t for k in ("benchmark", "evaluation", "comparison", "randomized controlled trial", "clinical trial")): return "evaluation"
    if any(k in t for k in ("efficient", "accelerat", "compress", "optimiz")): return "optimization"
    try:
        year = int(str(published)[:4])
        if (citations or 0) > 3000 and (CURRENT_YEAR - year) > 3: return "foundational"
    except (ValueError, TypeError): pass
    return "application"

def _weighted_score(paper: dict, orig_vec: list[float], other_vecs: list[list[float]]) -> float:
    vec = paper.get("abstract_vec")
    if vec is None: return 0.0

    relevance_orig = similarity(orig_vec, vec)
    relevance_others = max((similarity(v, vec) for v in other_vecs), default=0.0)

    relevance = 0.6 * relevance_orig + 0.4 * relevance_others
    citation = _citation_score(paper.get("citation_count", 0))
    recency = _recency_score(paper.get("published", ""))

    score = 0.70 * relevance + 0.05 * citation + 0.25 * recency

    penalty = paper.get("_validation_penalty")
    if penalty: score *= penalty
    return score

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

def _deduplicate_papers(papers: list[dict]) -> list[dict]:
    seen_ids = set()
    seen_titles = set()
    deduped = []
    for p in sorted(papers, key=lambda p: p.get("final_score", 0), reverse=True):
        arxiv_id = p.get("arxiv_id")
        openalex_id = p.get("openalex_id")
        norm = p["title"].strip().lower()

        if arxiv_id and arxiv_id in seen_ids: continue
        if openalex_id and openalex_id in seen_ids: continue
        if norm in seen_titles: continue

        if arxiv_id: seen_ids.add(arxiv_id)
        if openalex_id: seen_ids.add(openalex_id)
        seen_titles.add(norm)
        deduped.append(p)
    return deduped

def rank_node(state: AgentState) -> AgentState:
    papers = state["raw_search_results"]
    is_uploaded_only = state.get("evidence_mode") == "uploaded"

    if not papers:
        return {
            **state,
            "ranked_papers": [],
            "needs_retry": False if is_uploaded_only else True,
            "papers_below_threshold": 0,
            "low_confidence_results": False,
        }

    original_query = state["query"]
    search_queries = state.get("search_queries", [original_query])

    orig_vec = state.get("query_embedding")
    if orig_vec is None:
        orig_vec = embed_texts([original_query])[0]
    other_queries = [q for q in search_queries if q != original_query]
    other_vecs = embed_texts(other_queries) if other_queries else []

    valid_papers = [p for p in papers if _has_valid_abstract(p)]
    invalid_papers = [p for p in papers if not _has_valid_abstract(p)]

    if valid_papers:
        abstracts = [p["summary"][:500] for p in valid_papers]
        abstract_vecs = embed_texts(abstracts)
        for p, vec in zip(valid_papers, abstract_vecs):
            p["abstract_vec"] = vec

    for p in invalid_papers:
        p["abstract_vec"] = None
        p["_no_abstract"] = True

    all_papers = valid_papers + invalid_papers
    for p in all_papers:
        p["paper_type"] = _infer_paper_type(p["title"], p.get("citation_count", 0), p.get("published", ""))
        p["final_score"] = round(_weighted_score(p, orig_vec, other_vecs), 3)
        if p.get("_no_abstract"):
            p["final_score"] = min(p["final_score"], 0.2)

    deduped = _deduplicate_papers(all_papers)
    prefiltered_before_threshold = deduped[:PRE_FILTER_N]

    prefiltered = []
    tier_used = None
    for tier in _RELAXATION_TIERS:
        effective_threshold = max(settings.MIN_FINAL_SCORE * tier, _ABSOLUTE_FLOOR)
        candidates = [p for p in prefiltered_before_threshold if p["final_score"] >= effective_threshold]
        if candidates:
            prefiltered = candidates
            tier_used = tier
            break

    low_confidence_results = tier_used is not None and tier_used < 1.0

    if len(prefiltered) < settings.TOP_K_PAPERS_MIN and not is_uploaded_only:
        top_ids = [p.get("openalex_id") for p in deduped[:3] if p.get("openalex_id")]
        if top_ids:
            print(f"[rank] Few papers found ({len(prefiltered)}). Expanding via OpenAlex citation graph for IDs: {top_ids}")
            extra_papers = fetch_openalex_citation_graph(top_ids, limit_per_paper=3)

            if extra_papers:
                extra_valid = [p for p in extra_papers if _has_valid_abstract(p)]
                extra_invalid = [p for p in extra_papers if not _has_valid_abstract(p)]

                if extra_valid:
                    extra_abstracts = [p["summary"][:500] for p in extra_valid]
                    extra_vecs = embed_texts(extra_abstracts)
                    for p, vec in zip(extra_valid, extra_vecs):
                        p["abstract_vec"] = vec

                for p in extra_invalid:
                    p["abstract_vec"] = None
                    p["_no_abstract"] = True

                for p in extra_valid + extra_invalid:
                    p["final_score"] = round(_weighted_score(p, orig_vec, other_vecs), 3)
                    if p.get("_no_abstract"):
                        p["final_score"] = min(p["final_score"], 0.2)
                    p["paper_type"] = _infer_paper_type(p["title"], p.get("citation_count", 0), p.get("published", ""))
                    p["_from_citation_graph"] = True

                all_papers.extend(extra_valid + extra_invalid)
                deduped = _deduplicate_papers(all_papers)
                prefiltered = [p for p in deduped if p["final_score"] >= max(settings.MIN_FINAL_SCORE * 0.45, _ABSOLUTE_FLOOR)]

    target_k = min(len(prefiltered), settings.TOP_K_PAPERS_MAX)
    vecs_by_title = {p["title"]: p["abstract_vec"] for p in prefiltered if p.get("abstract_vec") is not None}
    top_k = _mmr_select(prefiltered, vecs_by_title, target_k) if prefiltered else []

    needs_retry = (
        not is_uploaded_only
        and len(top_k) < settings.TOP_K_PAPERS_MIN
        and state.get("search_attempts", 0) < state.get("max_search_attempts", 2)
    )

    return {
        **state,
        "ranked_papers": top_k,
        "needs_retry": state.get("needs_retry", False) or needs_retry,
        "papers_below_threshold": len(deduped) - len(prefiltered),
        "low_confidence_results": low_confidence_results,
    }