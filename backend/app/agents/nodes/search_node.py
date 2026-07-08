import hashlib
import time
from concurrent.futures import ThreadPoolExecutor

from app.agents.state import AgentState
from app.services.paper_search import search_arxiv, search_semantic_scholar, get_seminal_papers

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


def search_node(state: AgentState) -> AgentState:
    query = state.get("refined_query") or state["query"]

    cached = _get_cached(query)
    if cached is not None:
        return {
            **state,
            "raw_search_results": cached,
            "search_attempts": state.get("search_attempts", 0) + 1,
        }

    seminal = get_seminal_papers(query)

    with ThreadPoolExecutor(max_workers=2) as ex:
        arxiv_future = ex.submit(search_arxiv, query)
        ss_future = ex.submit(search_semantic_scholar, query)
        arxiv_results = arxiv_future.result()
        ss_results = ss_future.result()

    combined = {}
    for p in seminal + ss_results + arxiv_results:
        key = p["title"].strip().lower()
        if key not in combined or p.get("citation_count", 0) > combined[key].get("citation_count", 0):
            combined[key] = p

    all_results = list(combined.values())
    _set_cached(query, all_results)

    return {
        **state,
        "raw_search_results": all_results,
        "search_attempts": state.get("search_attempts", 0) + 1,
    }
