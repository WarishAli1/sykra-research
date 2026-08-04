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

_FOUNDATION_SOURCE_BONUS = {
    "citation_backtrack": 0.20,
    "precision": 0.10,
    "generic": 0.0,
}


def _paper_key(p: dict) -> str:
    return p.get("link") or p.get("title", "").strip().lower()


def _has_valid_abstract(paper: dict) -> bool:
    return len(paper.get("summary", "").strip()) >= MIN_ABSTRACT_LENGTH


def _citation_score(citations) -> float:
    return math.log(1 + (citations or 0)) / math.log(1 + 100_000)


def _recency_score(published: str) -> float:
    try:
        year = int(str(published)[:4])
    except (ValueError, TypeError):
        return 0.3

    return max(0.0, 1 - max(CURRENT_YEAR - year, 0) / 15)


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


def _foundation_eligible(paper: dict) -> bool:
    rel = float(paper.get("_relevance_orig", 0.0) or 0.0)
    cites = int(paper.get("citation_count", 0) or 0)
    src = paper.get("_foundational_source")

    if src == "citation_backtrack":
        return rel >= 0.12 or cites >= 500

    if src == "precision":
        return rel >= 0.18 or (cites >= 1000 and rel >= 0.10)

    return rel >= 0.20 or (cites >= 500 and rel >= 0.15)


def _foundation_priority(paper: dict) -> float:
    rel = float(paper.get("_relevance_orig", 0.0) or 0.0)
    cite = _citation_score(paper.get("citation_count", 0))
    bonus = _FOUNDATION_SOURCE_BONUS.get(paper.get("_foundational_source"), 0.0)

    return bonus + (0.55 * rel) + (0.45 * cite)


def _weighted_score(paper: dict, orig_vec: list[float], other_vecs: list[list[float]]) -> float:
    vec = paper.get("abstract_vec")

    if vec is None:
        paper["_relevance_orig"] = 0.0
        paper["_relevance_combined"] = 0.0
        return 0.0

    relevance_orig = similarity(orig_vec, vec)
    relevance_others = max((similarity(v, vec) for v in other_vecs), default=0.0)
    relevance = 0.6 * relevance_orig + 0.4 * relevance_others

    citation = _citation_score(paper.get("citation_count", 0))
    recency = _recency_score(paper.get("published", ""))

    if paper.get("_foundational_candidate"):
        score = 0.70 * relevance + 0.25 * citation + 0.05 * recency
    else:
        score = 0.70 * relevance + 0.05 * citation + 0.25 * recency

    if paper.get("_validation_penalty"):
        score *= paper["_validation_penalty"]

    paper["_relevance_orig"] = round(relevance_orig, 3)
    paper["_relevance_combined"] = round(relevance, 3)

    return score


def _embed_missing_abstracts(papers: list[dict], text_fn) -> None:
    need = [p for p in papers if p.get("abstract_vec") is None]

    if not need:
        return

    texts = [text_fn(p) for p in need]
    vecs = embed_texts(texts)

    for p, vec in zip(need, vecs):
        p["abstract_vec"] = vec


def _mmr_select(papers: list[dict], vecs_by_title: dict, k: int, lam: float = MMR_LAMBDA) -> list[dict]:
    selected, remaining, missing = [], [], []

    for p in papers:
        if p["title"] in vecs_by_title:
            remaining.append(p)
        else:
            missing.append(p)

    while remaining and len(selected) < k:
        if not selected:
            best = max(remaining, key=lambda p: p["final_score"])
        else:
            def mmr(p):
                return (
                    lam * p["final_score"]
                    - (1 - lam) * max(
                        similarity(vecs_by_title[p["title"]], vecs_by_title[s["title"]])
                        for s in selected
                    )
                )

            best = max(remaining, key=mmr)

        selected.append(best)
        remaining.remove(best)

    if len(selected) < k and missing:
        selected.extend(
            sorted(missing, key=lambda p: p.get("final_score", 0), reverse=True)[: k - len(selected)]
        )

    return selected


def _deduplicate_papers(papers: list[dict]) -> list[dict]:
    seen_ids, seen_titles, deduped = set(), set(), []

    for p in sorted(papers, key=lambda p: p.get("final_score", 0), reverse=True):
        arxiv_id = p.get("arxiv_id")
        openalex_id = p.get("openalex_id")
        norm = p["title"].strip().lower()

        if arxiv_id and arxiv_id in seen_ids:
            continue

        if openalex_id and openalex_id in seen_ids:
            continue

        if norm in seen_titles:
            continue

        if arxiv_id:
            seen_ids.add(arxiv_id)

        if openalex_id:
            seen_ids.add(openalex_id)

        seen_titles.add(norm)
        deduped.append(p)

    return deduped


def _add_foundational_to_prefiltered(prefiltered: list[dict], pool: list[dict], limit: int = 2) -> list[dict]:
    existing = {_paper_key(p) for p in prefiltered}
    extra = []

    candidates = [
        p for p in pool
        if p.get("_foundational_candidate") and _foundation_eligible(p)
    ]

    candidates.sort(key=_foundation_priority, reverse=True)

    for p in candidates:
        key = _paper_key(p)

        if key in existing:
            continue

        extra.append(p)
        existing.add(key)

        if len(extra) >= limit:
            break

    return prefiltered + extra


def _ensure_foundational(top_k: list[dict], pool: list[dict], target_k: int) -> list[dict]:
    if not top_k:
        return top_k

    max_found = 2 if target_k >= 8 else 1

    current = sum(1 for p in top_k if p.get("_foundational_candidate"))
    if current >= max_found:
        return top_k

    selected_keys = {_paper_key(p) for p in top_k}

    candidates = [
        p for p in pool
        if p.get("_foundational_candidate")
        and _paper_key(p) not in selected_keys
        and _foundation_eligible(p)
    ]

    candidates.sort(key=_foundation_priority, reverse=True)

    need = max_found - current

    for p in candidates[:need]:
        if len(top_k) < max(target_k, 1):
            top_k.append(p)
        else:
            non_found = [i for i, x in enumerate(top_k) if not x.get("_foundational_candidate")]

            if not non_found:
                break

            worst = min(non_found, key=lambda i: top_k[i].get("final_score", 0))
            top_k[worst] = p

        selected_keys.add(_paper_key(p))

    return top_k


def rank_node(state: AgentState) -> AgentState:
    papers = state.get("raw_search_results", [])
    is_uploaded_only = state.get("evidence_mode") == "uploaded"

    if not papers:
        return {
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

    for p in invalid_papers:
        if p.get("_foundational_candidate") and p.get("title", "").strip():
            p["_title_embed"] = True

    title_embed_papers = [p for p in invalid_papers if p.get("_title_embed")]
    no_vec_papers = [p for p in invalid_papers if not p.get("_title_embed")]

    _embed_missing_abstracts(valid_papers, lambda p: p["summary"][:500])
    _embed_missing_abstracts(title_embed_papers, lambda p: p["title"])

    for p in no_vec_papers:
        p["abstract_vec"] = None
        p["_no_abstract"] = True

    all_papers = valid_papers + title_embed_papers + no_vec_papers

    for p in all_papers:
        p["paper_type"] = _infer_paper_type(
            p["title"],
            p.get("citation_count", 0),
            p.get("published", ""),
        )

        p["final_score"] = round(_weighted_score(p, orig_vec, other_vecs), 3)

        if p.get("_no_abstract"):
            p["final_score"] = min(max(p["final_score"], 0.2), 0.25)

    deduped = _deduplicate_papers(all_papers)

    prefiltered_before_threshold = deduped[:PRE_FILTER_N]
    prefiltered, tier_used = [], None

    for tier in _RELAXATION_TIERS:
        effective_threshold = max(settings.MIN_FINAL_SCORE * tier, _ABSOLUTE_FLOOR)

        candidates = [
            p for p in prefiltered_before_threshold
            if p["final_score"] >= effective_threshold
        ]

        if candidates:
            prefiltered = candidates
            tier_used = tier
            break

    prefiltered = _add_foundational_to_prefiltered(prefiltered, deduped, limit=2)

    low_confidence_results = tier_used is not None and tier_used < 1.0

    if len(prefiltered) < settings.TOP_K_PAPERS_MIN and not is_uploaded_only:
        top_ids = [p.get("openalex_id") for p in deduped[:3] if p.get("openalex_id")]

        if top_ids:
            extra_papers = fetch_openalex_citation_graph(top_ids, limit_per_paper=3)

            if extra_papers:
                extra_valid = [p for p in extra_papers if _has_valid_abstract(p)]
                extra_invalid = [p for p in extra_papers if not _has_valid_abstract(p)]

                _embed_missing_abstracts(extra_valid, lambda p: p["summary"][:500])

                for p in extra_invalid:
                    p["abstract_vec"] = None
                    p["_no_abstract"] = True

                for p in extra_valid + extra_invalid:
                    p["final_score"] = round(_weighted_score(p, orig_vec, other_vecs), 3)

                    if p.get("_no_abstract"):
                        p["final_score"] = min(max(p["final_score"], 0.2), 0.25)

                    p["paper_type"] = _infer_paper_type(
                        p["title"],
                        p.get("citation_count", 0),
                        p.get("published", ""),
                    )

                    p["_from_citation_graph"] = True

                all_papers.extend(extra_valid + extra_invalid)

                deduped = _deduplicate_papers(all_papers)

                prefiltered = [
                    p for p in deduped
                    if p["final_score"] >= max(settings.MIN_FINAL_SCORE * 0.45, _ABSOLUTE_FLOOR)
                ]

                prefiltered = _add_foundational_to_prefiltered(prefiltered, deduped, limit=2)

                low_confidence_results = True

    target_k_setting = int(state.get("target_paper_k") or settings.TOP_K_PAPERS_MAX)
    target_k_setting = max(settings.TOP_K_PAPERS_MIN, target_k_setting)
    target_k_setting = min(settings.TOP_K_PAPERS_MAX, target_k_setting)

    target_k = min(len(prefiltered), target_k_setting)

    vecs_by_title = {
        p["title"]: p["abstract_vec"]
        for p in prefiltered
        if p.get("abstract_vec") is not None
    }

    top_k = _mmr_select(prefiltered, vecs_by_title, target_k) if prefiltered else []
    top_k = _ensure_foundational(top_k, deduped, target_k)

    forced = [p["title"] for p in top_k if p.get("_foundational_candidate")]
    print(f"[rank:foundation] final top_k foundational={forced}")

    needs_retry = (
        not is_uploaded_only
        and len(top_k) < settings.TOP_K_PAPERS_MIN
        and state.get("search_attempts", 0) < state.get("max_search_attempts", 2)
    )

    return {
        "ranked_papers": top_k,
        "needs_retry": state.get("needs_retry", False) or needs_retry,
        "papers_below_threshold": len(deduped) - len(prefiltered),
        "low_confidence_results": low_confidence_results,
    }