import hashlib
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError

from app.agents.state import AgentState
from app.services.paper_search import search_arxiv, search_openalex
from app.services.embeddings import embed_texts, similarity

ACRONYM_EXPANSIONS = {
    "GANs": "generative adversarial networks",
    "RAG": "retrieval augmented generation",
    "CFG": "classifier-free guidance",
}

_query_cache: dict[str, tuple[float, list[dict]]] = {}
CACHE_TTL_SECONDS = 3600


def _get_cached(query: str) -> list[dict] | None:
    key = hashlib.sha256(query.lower().encode()).hexdigest()
    entry = _query_cache.get(key)
    if entry and (time.time() - entry[0]) < CACHE_TTL_SECONDS:
        return entry[1]
    return None


def _set_cached(query: str, results: list[dict]):
    key = hashlib.sha256(query.lower().encode()).hexdigest()
    _query_cache[key] = (time.time(), results)


def expand_term(term: str) -> list[str]:
    if term in ACRONYM_EXPANSIONS:
        return [term, ACRONYM_EXPANSIONS[term]]
    return [term]


def search_node(state: AgentState) -> AgentState:
    raw_terms = state.get("search_terms") or [state.get("refined_query") or state["query"]]
    terms = list(dict.fromkeys(e for t in raw_terms for e in expand_term(t)))

    to_fetch = []
    per_term_results = {}
    for term in terms:
        cached = _get_cached(term)
        if cached is not None:
            per_term_results[term] = cached
        else:
            to_fetch.append(term)

    if to_fetch:
        with ThreadPoolExecutor(max_workers=min(len(to_fetch) * 2, 6)) as ex:
            futures = {}
            for term in to_fetch:
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

    all_results = {}
    for term, results in per_term_results.items():
        if not results:
            continue
        term_vec = embed_texts([term])[0]
        abstracts = [p.get("summary", "")[:500] or p["title"] for p in results]
        abstract_vecs = embed_texts(abstracts)
        scored = []
        for p, vec in zip(results, abstract_vecs):
            sim = similarity(term_vec, vec)
            if sim >= 0.4:
                scored.append((sim, p))
        candidates = [p for _, p in sorted(scored, key=lambda x: x[0], reverse=True)]
        term_lower = term.lower()
        is_single_word = len(term_lower.split()) == 1
        for p in candidates[:10]:
            if not p.get("title", "").strip():
                continue
            if is_single_word and term_lower not in p["title"].lower():
                continue
            key = p["title"].strip().lower()
            if key not in all_results or p.get("citation_count", 0) > all_results[key].get("citation_count", 0):
                p["_source_term"] = term
                all_results[key] = p

    return {
        **state,
        "raw_search_results": list(all_results.values()),
        "search_attempts": state.get("search_attempts", 0) + 1,
    }
