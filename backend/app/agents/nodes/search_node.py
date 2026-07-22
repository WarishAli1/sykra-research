import hashlib
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from app.agents.state import AgentState
from app.services.paper_search import search_arxiv, search_openalex
from app.services.embeddings import embed_texts, similarity

_query_cache: dict[str, tuple[float, list[dict]]] = {}
CACHE_TTL_SECONDS = 3600
MAX_PER_TERM = 30
MAX_TOTAL_CANDIDATES = 150

def _get_cached(query: str) -> list[dict] | None:
    key = hashlib.sha256(query.lower().encode()).hexdigest()
    entry = _query_cache.get(key)
    if entry and (time.time() - entry[0]) < CACHE_TTL_SECONDS: return entry[1]
    return None

def _set_cached(query: str, results: list[dict]):
    key = hashlib.sha256(query.lower().encode()).hexdigest()
    _query_cache[key] = (time.time(), results)

def search_node(state: AgentState) -> AgentState:
    if state.get("evidence_mode") == "uploaded":
        return {**state, "raw_search_results": [], "needs_retry": False}

    terms = state.get("search_queries") or state.get("search_terms") or [state["query"]]
    terms = list(dict.fromkeys(terms))

    to_fetch = []
    per_term_results = {}
    for term in terms:
        cached = _get_cached(term)
        if cached is not None: per_term_results[term] = cached
        else: to_fetch.append(term)

    if to_fetch:
        with ThreadPoolExecutor(max_workers=min(len(to_fetch) * 2, 8)) as ex:
            futures = {}
            for term in to_fetch:
                if state.get("likely_cs_relevant", True):
                    futures[ex.submit(search_arxiv, term)] = ("arxiv", term)
                futures[ex.submit(search_openalex, term, 10, True)] = ("openalex", term)

            gathered = {term: [] for term in to_fetch}
            for future in as_completed(futures):
                source, term = futures[future]
                try:
                    res = future.result(timeout=15)
                except (TimeoutError, Exception):
                    res = []
                gathered[term].extend(res)

        for term, results in gathered.items():
            per_term_results[term] = results
            _set_cached(term, results)

    seen_ids = set()
    seen_titles = set()
    all_results = {}

    for term, results in per_term_results.items():
        if not results: continue

        term_vec = embed_texts([term])[0]
        abstracts = [p.get("summary", "")[:300] or p["title"] for p in results]
        abstract_vecs = embed_texts(abstracts)

        for p, vec in zip(results, abstract_vecs):
            sim = similarity(term_vec, vec)
            if sim < 0.35: continue
            arxiv_id = p.get("arxiv_id")
            openalex_id = p.get("openalex_id")
            norm_title = p.get("title", "").strip().lower()

            if not norm_title: continue

            if arxiv_id and arxiv_id in seen_ids: continue
            if openalex_id and openalex_id in seen_ids: continue
            if norm_title in seen_titles: continue

            if arxiv_id: seen_ids.add(arxiv_id)
            if openalex_id: seen_ids.add(openalex_id)
            seen_titles.add(norm_title)

            p["_source_term"] = term
            p["_initial_sim"] = sim
            all_results[norm_title] = p

    combined = list(all_results.values())[:MAX_TOTAL_CANDIDATES]

    mandatory_kws = state.get("mandatory_domain_keywords")
    domain_full = state.get("domain_full", "")
    if mandatory_kws:
        hard_filtered = [
            p for p in combined
            if any(kw in (p.get("title", "") + " " + p.get("summary", "")).lower() for kw in mandatory_kws)
        ]
        if len(hard_filtered) < 5 and domain_full:
            soft_words = domain_full.lower().split()
            soft_filtered = [
                p for p in combined if p not in hard_filtered
                and any(w in (p.get("title", "") + " " + p.get("summary", "")).lower() for w in soft_words)
            ]
            combined = hard_filtered + soft_filtered[:max(0, 5 - len(hard_filtered))]
        else:
            combined = hard_filtered

    search_attempts = state.get("search_attempts", 0) + 1
    needs_retry = len(combined) < 5 and search_attempts < state.get("max_search_attempts", 2)

    return {
        **state,
        "raw_search_results": combined,
        "search_attempts": search_attempts,
        "needs_retry": needs_retry,
    }