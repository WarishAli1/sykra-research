import asyncio
import hashlib
import re
import threading
import time

from app.agents.state import AgentState
from app.services.paper_search import (
    search_arxiv_async,
    search_openalex_async,
    search_openalex_foundational_async,
    fetch_referenced_work_ids_async,
    fetch_openalex_works_by_ids_async,
    sanitize_openalex_search,
)
from app.services.embeddings import embed_texts, similarity
from app.services.embedding_cache import batch_get_or_compute
from app.services import semantic_cache
from app.services import request_dedup
from app.config import settings

_query_cache: dict[str, tuple[float, list[dict]]] = {}
_cache_lock = threading.Lock()
CACHE_TTL_SECONDS = 3600

MAX_TOTAL_CANDIDATES = 150
SIM_THRESH = 0.35
FOUNDATION_SIM_THRESH = 0.22
FOUNDATION_BACKTRACK_SIM_THRESH = 0.15
FOUNDATION_GUARANTEE_SIM = 0.15

MAX_FOUNDATION_TERMS = 5 
FOUNDATION_PER_TERM = 12 

CANDIDATE_PRE_EMBED = 120

ENABLE_FOUNDATION_BACKTRACK = False 
MAX_BACKTRACK_ANCHORS = 2
MAX_REFERENCED_PER_ANCHOR = 25
MAX_BACKTRACK_IDS = 50
MAX_BACKTRACK_WORKS = 50

FAST_MAX_QUERIES = 3
FAST_MAX_FOUNDATION_TERMS = 2
FAST_CANDIDATE_PRE_EMBED = 40
FAST_FOUNDATION_APPEND = 6
FAST_ARXIV_RESULTS = 8


def _paper_key(p: dict) -> str:
    return p.get("link") or p.get("title", "").strip().lower()


def _cache_key(query: str, kind: str) -> str:
    return hashlib.sha256(f"{kind}:{query.lower()}".encode()).hexdigest()


def _get_cached(query: str, kind: str = "normal") -> list[dict] | None:
    with _cache_lock:
        entry = _query_cache.get(_cache_key(query, kind))

    if entry and (time.time() - entry[0]) < CACHE_TTL_SECONDS:
        return entry[1]

    return None


def _set_cached(query: str, results: list[dict], kind: str = "normal") -> None:
    with _cache_lock:
        _query_cache[_cache_key(query, kind)] = (time.time(), results)


def _safe_results(result) -> list[dict]:
    if isinstance(result, Exception):
        return []
    return result or []


def _foundation_search_terms(state: AgentState) -> list[str]:
    qu = state.get("query_understanding") or {}

    main_topic = (qu.get("main_topic") or "").strip()
    domain = (qu.get("application_domain") or "").strip()
    methods = [m.strip() for m in (qu.get("methods_techniques") or []) if m and m.strip()]
    entities = [e.strip() for e in (qu.get("entities") or []) if e and e.strip()]

    terms = []

    if main_topic and domain:
        terms.append(f"{main_topic} {domain}")

    if main_topic and methods:
        terms.append(f"{main_topic} {methods[0]}")

    if main_topic:
        terms.append(main_topic)

    for e in entities[:2]:
        terms.append(e)

    for m in methods[:2]:
        terms.append(m)

    cleaned_query = sanitize_openalex_search(state.get("query", ""), max_words=6)
    if cleaned_query:
        terms.append(cleaned_query)

    raw_q = state.get("query", "").lower()
    if " and " in raw_q or " vs " in raw_q or " or " in raw_q:
        parts = re.split(r"\s+(?:and|vs|or)\s+", raw_q)
        for part in parts:
            clean_part = sanitize_openalex_search(part, max_words=4)
            if clean_part and len(clean_part) > 2:
                terms.append(clean_part)

    clean, seen = [], set()

    for t in terms:
        t = (t or "").strip()
        key = t.lower()

        if t and key not in seen and len(t) <= 120:
            seen.add(key)
            clean.append(t)

    return clean[:MAX_FOUNDATION_TERMS]


def _mark_foundational(p: dict, source: str) -> dict:
    p["_foundational_candidate"] = True

    rank = {
        "citation_backtrack": 3,
        "precision": 2,
        "generic": 1,
    }

    prev = p.get("_foundational_source")
    if not prev or rank.get(source, 0) > rank.get(prev, 0):
        p["_foundational_source"] = source

    return p


def _merge_foundational_into_deduped(deduped, seen_ids, seen_titles, papers, source):
    for p in papers:
        norm = p.get("title", "").strip().lower()
        if not norm:
            continue

        arxiv_id, openalex_id = p.get("arxiv_id"), p.get("openalex_id")

        existing = deduped.get(norm)
        if existing:
            _mark_foundational(existing, source)

            if (p.get("citation_count") or 0) > (existing.get("citation_count") or 0):
                existing["citation_count"] = p.get("citation_count")
                existing["source"] = existing.get("source") or p.get("source")

            continue

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

        _mark_foundational(p, source)
        deduped[norm] = p


async def _fetch_normal_term(term: str, arxiv_limit: int | None) -> tuple[str, list[dict]]:
    arxiv_task = asyncio.create_task(search_arxiv_async(term, arxiv_limit))
    openalex_task = asyncio.create_task(search_openalex_async(term, 10, True))

    arxiv_res, openalex_res = await asyncio.gather(
        arxiv_task,
        openalex_task,
        return_exceptions=True,
    )

    return term, _safe_results(arxiv_res) + _safe_results(openalex_res)


async def _fetch_precision_term(term: str) -> tuple[str, list[dict]]:
    try:
        results = await search_openalex_foundational_async(term, FOUNDATION_PER_TERM)
    except Exception:
        results = []

    return term, results or []


async def _materialize_cached_search(state: AgentState, cached: dict) -> dict:
    raw = cached.get("raw_search_results", []) or []
    query_embedding = cached.get("query_embedding")

    if not query_embedding:
        query_embedding = (await asyncio.to_thread(embed_texts, [state["query"]]))[0]

    paired = await asyncio.to_thread(
        batch_get_or_compute,
        raw[:MAX_TOTAL_CANDIDATES],
        embed_texts,
    )

    for paper, vec in paired:
        paper["_initial_sim"] = similarity(query_embedding, vec)
        paper["abstract_vec"] = vec

    combined = [p for p, _ in paired]

    return {
        "raw_search_results": combined,
        "search_attempts": state.get("search_attempts", 0) + 1,
        "needs_retry": False,
        "query_embedding": query_embedding,
        "search_cache_hit": True,
    }


async def _search_core_async(state: AgentState, scope: str) -> dict:
    mode = state.get("response_mode", "normal")
    evidence_mode = state.get("evidence_mode", "literature")
    is_fast = mode not in ("researched", "graph_research")

    target_k = int(state.get("target_paper_k") or settings.TOP_K_PAPERS_MAX)

    terms = state.get("search_queries") or state.get("search_terms") or [state["query"]]
    terms = list(dict.fromkeys(terms))

    if is_fast:
        max_queries = min(FAST_MAX_QUERIES, max(2, target_k))
        terms = terms[:max_queries]

    foundation_terms = _foundation_search_terms(state)

    if is_fast:
        max_foundation_terms = min(FAST_MAX_FOUNDATION_TERMS, max(1, target_k - 2))
        foundation_terms = foundation_terms[:max_foundation_terms]

    arxiv_limit = FAST_ARXIV_RESULTS if is_fast else max(settings.ARXIV_MAX_RESULTS, target_k * 2)

    print(
        f"[search] mode={mode} fast={is_fast} target_k={target_k} "
        f"terms={len(terms)} foundation_terms={foundation_terms}"
    )

    per_term_results = {t: _get_cached(t, "normal") or [] for t in terms}
    to_fetch = [t for t in terms if _get_cached(t, "normal") is None]

    if to_fetch:
        tasks = [_fetch_normal_term(term, arxiv_limit) for term in to_fetch]
        fetched = await asyncio.gather(*tasks, return_exceptions=True)

        for item in fetched:
            if isinstance(item, Exception):
                continue

            term, results = item
            _set_cached(term, results, "normal")
            per_term_results[term] = results

    precision_results = []
    cached_precision = {t: _get_cached(t, "foundation_v2") or [] for t in foundation_terms}
    to_fetch_precision = [t for t in foundation_terms if _get_cached(t, "foundation_v2") is None]

    if to_fetch_precision:
        tasks = [_fetch_precision_term(t) for t in to_fetch_precision]
        fetched_precision = await asyncio.gather(*tasks, return_exceptions=True)

        for item in fetched_precision:
            if isinstance(item, Exception):
                continue

            term, results = item
            _set_cached(term, results, "foundation_v2")
            cached_precision[term] = results

    for term, results in cached_precision.items():
        for p in results:
            p["_source_term"] = term
            _mark_foundational(p, "precision")
            precision_results.append(p)

    seen_ids, seen_titles = set(), set()
    deduped = {}

    for term, results in per_term_results.items():
        for p in results:
            arxiv_id, openalex_id = p.get("arxiv_id"), p.get("openalex_id")
            norm = p.get("title", "").strip().lower()

            if not norm:
                continue

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

            p["_source_term"] = term
            deduped[norm] = p

    _merge_foundational_into_deduped(
        deduped,
        seen_ids,
        seen_titles,
        precision_results,
        "precision",
    )

    all_papers = list(deduped.values())

    query_words = [w for w in state["query"].lower().split() if len(w) > 3]

    if query_words:
        filtered = [p for p in all_papers if any(qw in p.get("title", "").lower() for qw in query_words)]

        if len(filtered) >= 5:
            filtered_keys = {_paper_key(p) for p in filtered}

            found = [
                p for p in all_papers
                if p.get("_foundational_candidate") and _paper_key(p) not in filtered_keys
            ]

            all_papers = filtered + found[:4]

    candidate_cap = FAST_CANDIDATE_PRE_EMBED if is_fast else CANDIDATE_PRE_EMBED
    candidate_cap = max(candidate_cap, target_k * 8)

    foundation_append = FAST_FOUNDATION_APPEND if is_fast else 12
    foundation_append = max(foundation_append, target_k)

    candidates = all_papers[:candidate_cap]

    foundation_candidates = [p for p in all_papers if p.get("_foundational_candidate")]
    foundation_candidates.sort(key=lambda x: x.get("citation_count", 0) or 0, reverse=True)

    candidate_keys = {_paper_key(p) for p in candidates}

    for p in foundation_candidates[:foundation_append]:
        key = _paper_key(p)
        if key not in candidate_keys:
            candidates.append(p)
            candidate_keys.add(key)

    query_embedding = (await asyncio.to_thread(embed_texts, [state["query"]]))[0]

    paired = await asyncio.to_thread(
        batch_get_or_compute,
        candidates,
        embed_texts,
    )

    for paper, vec in paired:
        paper["_initial_sim"] = similarity(query_embedding, vec)
        paper["abstract_vec"] = vec

    backtrack_results = []
    enable_backtrack = ENABLE_FOUNDATION_BACKTRACK and not is_fast

    if enable_backtrack:
        anchor_pool = [
            p for p, _ in paired
            if p.get("openalex_id") and not p.get("_foundational_candidate")
        ]

        anchor_pool.sort(
            key=lambda p: (p.get("_initial_sim", 0), p.get("citation_count", 0) or 0),
            reverse=True,
        )

        anchors = [
            p["openalex_id"] for p in anchor_pool
            if p.get("_initial_sim", 0) >= 0.40
        ][:MAX_BACKTRACK_ANCHORS]

        if not anchors:
            anchors = [p["openalex_id"] for p in anchor_pool[:MAX_BACKTRACK_ANCHORS]]

        if anchors:
            ref_ids = []

            tasks = [
                fetch_referenced_work_ids_async(aid, MAX_REFERENCED_PER_ANCHOR)
                for aid in anchors
            ]

            fetched_refs = await asyncio.gather(*tasks, return_exceptions=True)

            for ids in fetched_refs:
                if isinstance(ids, Exception):
                    continue

                for wid in ids or []:
                    if wid not in ref_ids:
                        ref_ids.append(wid)

                    if len(ref_ids) >= MAX_BACKTRACK_IDS:
                        break

            if ref_ids:
                works = await fetch_openalex_works_by_ids_async(ref_ids, limit=MAX_BACKTRACK_WORKS)

                for w in works:
                    w["_source_term"] = "citation_backtrack"
                    _mark_foundational(w, "citation_backtrack")

                backtrack_results = works

    paired_keys = {_paper_key(p) for p, _ in paired}
    to_embed_backtrack = []

    for p in backtrack_results:
        norm = p.get("title", "").strip().lower()
        if not norm:
            continue

        existing = deduped.get(norm)

        if existing:
            _mark_foundational(existing, "citation_backtrack")

            if (p.get("citation_count") or 0) > (existing.get("citation_count") or 0):
                existing["citation_count"] = p.get("citation_count")

            target = existing

        else:
            arxiv_id, openalex_id = p.get("arxiv_id"), p.get("openalex_id")

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

            deduped[norm] = p
            target = p

        key = _paper_key(target)
        if key not in paired_keys:
            to_embed_backtrack.append(target)
            paired_keys.add(key)

    if to_embed_backtrack:
        bp_paired = await asyncio.to_thread(
            batch_get_or_compute,
            to_embed_backtrack[:MAX_BACKTRACK_WORKS],
            embed_texts,
        )

        for paper, vec in bp_paired:
            paper["_initial_sim"] = similarity(query_embedding, vec)
            paper["abstract_vec"] = vec

        paired.extend(bp_paired)

    filtered_papers, seen_keys, foundational_pool = [], set(), []

    for paper, vec in paired:
        sim = paper.get("_initial_sim", 0.0)
        key = _paper_key(paper)

        if paper.get("_foundational_candidate"):
            foundational_pool.append(paper)

            src = paper.get("_foundational_source")
            cites = paper.get("citation_count", 0) or 0

            if src == "citation_backtrack" and (sim >= FOUNDATION_BACKTRACK_SIM_THRESH or cites >= 1000):
                if key not in seen_keys:
                    filtered_papers.append(paper)
                    seen_keys.add(key)

            elif src == "precision" and (sim >= FOUNDATION_SIM_THRESH or (cites >= 5000 and sim >= 0.12)):
                if key not in seen_keys:
                    filtered_papers.append(paper)
                    seen_keys.add(key)

            elif sim >= FOUNDATION_SIM_THRESH:
                if key not in seen_keys:
                    filtered_papers.append(paper)
                    seen_keys.add(key)

        else:
            if sim >= SIM_THRESH:
                if key not in seen_keys:
                    filtered_papers.append(paper)
                    seen_keys.add(key)

    if not any(p.get("_foundational_candidate") for p in filtered_papers):
        top_found = sorted(
            foundational_pool,
            key=lambda p: (
                {"citation_backtrack": 2, "precision": 1}.get(p.get("_foundational_source"), 0),
                p.get("citation_count", 0),
                p.get("_initial_sim", 0),
            ),
            reverse=True,
        )[:2]

        for p in top_found:
            key = _paper_key(p)
            if key in seen_keys:
                continue

            if (
                p.get("_foundational_source") == "citation_backtrack"
                or p.get("_initial_sim", 0) >= FOUNDATION_GUARANTEE_SIM
            ):
                filtered_papers.append(p)
                seen_keys.add(key)

    if len(filtered_papers) < 5:
        for p, vec in paired:
            key = _paper_key(p)
            if key in seen_keys:
                continue

            filtered_papers.append(p)
            seen_keys.add(key)

    combined = filtered_papers[:MAX_TOTAL_CANDIDATES]

    search_attempts = state.get("search_attempts", 0) + 1
    needs_retry = len(combined) < 5 and search_attempts < state.get("max_search_attempts", 2)

    found = [p for p in combined if p.get("_foundational_candidate")]

    print(
        f"[search:foundation] kept {len(combined)} candidates; "
        f"foundational={len(found)}; "
        f"top_foundational={[p.get('title', '')[:60] for p in found[:3]]}"
    )

    if (
        settings.SEMANTIC_CACHE_ENABLED
        and evidence_mode != "uploaded"
        and combined
    ):
        await asyncio.to_thread(
            semantic_cache.set_search_cache,
            state["query"],
            scope,
            combined,
            query_embedding,
        )

    return {
        "raw_search_results": combined,
        "search_attempts": search_attempts,
        "needs_retry": needs_retry,
        "query_embedding": query_embedding,
        "search_cache_hit": False,
    }


async def search_node(state: AgentState) -> AgentState:
    if state.get("evidence_mode") == "uploaded":
        return {
            "raw_search_results": [],
            "needs_retry": False,
            "search_cache_hit": False,
        }

    mode = state.get("response_mode", "normal")
    evidence_mode = state.get("evidence_mode", "literature")
    query = state.get("query", "")

    scope = f"search:{mode}:{evidence_mode}"

    if settings.SEMANTIC_CACHE_ENABLED and evidence_mode != "uploaded":
        cached = await asyncio.to_thread(
            semantic_cache.get_search_cache,
            query,
            scope,
        )

        if cached:
            print(f"[search] semantic cache hit similarity={cached.get('_cache_similarity', 0):.3f}")
            return await _materialize_cached_search(state, cached)


    dedup_key = semantic_cache.make_scope_key(query, scope)

    if settings.REQUEST_DEDUP_ENABLED:
        return await request_dedup.execute_once_async(
            dedup_key,
            lambda: _search_core_async(state, scope),
        )

    return await _search_core_async(state, scope)