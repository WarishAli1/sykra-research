import asyncio
import re

import arxiv
import httpx

from app.config import settings

_STOP_WORDS = {
    "what", "is", "are", "was", "were", "a", "an", "the", "how", "does", "do",
    "why", "when", "which", "who", "whom", "of", "in", "on", "for", "to",
    "and", "or", "with", "by", "from", "as", "at", "be", "this", "that",
    "these", "those", "explain", "define", "describe", "overview",
    "introduction", "meaning", "works", "work", "used", "use",
}

_LIMITS = httpx.Limits(
    max_keepalive_connections=20,
    max_connections=100,
)

_sync_client = httpx.Client(
    timeout=15,
    limits=_LIMITS,
)

_async_client: httpx.AsyncClient | None = None


def _get_async_client() -> httpx.AsyncClient:
    global _async_client
    if _async_client is None:
        _async_client = httpx.AsyncClient(
            timeout=15,
            limits=_LIMITS,
        )
    return _async_client


async def aclose_http_clients() -> None:
    global _async_client

    try:
        _sync_client.close()
    except Exception:
        pass

    if _async_client is not None:
        try:
            await _async_client.aclose()
        except Exception:
            pass
        _async_client = None


def _normalize_link(url: str) -> str:
    return url.replace("http://", "https://", 1) if url.startswith("http://") else url


def _extract_arxiv_id(link: str) -> str:
    if not link:
        return ""
    match = re.search(r"(\d{4}\.\d{4,5})(v\d+)?", link)
    return match.group(1) if match else ""


def _extract_openalex_id(link: str) -> str:
    if not link:
        return ""
    match = re.search(r"openalex.org/(W\d+)", link)
    return match.group(1) if match else ""


def _extract_openalex_wid(url_or_id: str) -> str:
    if not url_or_id:
        return ""
    match = re.search(r"(W\d+)", url_or_id)
    return match.group(1) if match else ""


def _reconstruct_abstract(inverted_index: dict | None) -> str:
    if not inverted_index:
        return ""

    positions = {}
    for word, idxs in inverted_index.items():
        for i in idxs:
            positions[i] = word

    return " ".join(positions[i] for i in sorted(positions))


def _format_openalex_work(w: dict) -> dict:
    oa = w.get("open_access") or {}
    authors = []

    for a in w.get("authorships", []):
        author = a.get("author") or {}
        name = author.get("display_name")
        if name:
            authors.append(name)

    return {
        "title": w.get("title") or "",
        "authors": authors,
        "summary": _reconstruct_abstract(w.get("abstract_inverted_index")),
        "link": w.get("id", ""),
        "pdf_url": _normalize_link(oa.get("oa_url") or ""),
        "published": str(w.get("publication_year", "")),
        "citation_count": w.get("cited_by_count", 0) or 0,
        "source": "openalex",
        "openalex_id": _extract_openalex_id(w.get("id", "")),
        "arxiv_id": "",
    }


def sanitize_openalex_search(text: str, max_words: int = 8) -> str:
    text = re.sub(r"[^\w\s+#-]", " ", text or "")
    words = [w for w in text.lower().split() if w]
    kept = [w for w in words if w not in _STOP_WORDS]

    if not kept:
        kept = words

    return " ".join(kept[:max_words]).strip()


def search_arxiv(query: str, max_results: int | None = None) -> list[dict]:
    try:
        search = arxiv.Search(
            query=query,
            max_results=max_results or settings.ARXIV_MAX_RESULTS,
            sort_by=arxiv.SortCriterion.Relevance,
        )

        results = []
        for r in search.results():
            link = _normalize_link(r.entry_id)
            results.append({
                "title": r.title,
                "authors": [a.name for a in r.authors],
                "summary": r.summary,
                "link": link,
                "pdf_url": _normalize_link(r.pdf_url),
                "published": str(r.published.date()),
                "citation_count": 0,
                "source": "arxiv",
                "arxiv_id": _extract_arxiv_id(link),
                "openalex_id": "",
            })

        return results

    except Exception:
        return []


def search_openalex(query: str, limit: int = 10, sort_by_citations: bool = False) -> list[dict]:
    url = "https://api.openalex.org/works"
    params = {"search": query, "per_page": limit}

    if sort_by_citations:
        params["sort"] = "cited_by_count:desc"

    try:
        resp = _sync_client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json().get("results", [])
        return [_format_openalex_work(w) for w in data]
    except Exception:
        return []


def search_openalex_foundational(query: str, limit: int = 10) -> list[dict]:
    sanitized = sanitize_openalex_search(query, max_words=8)
    if not sanitized or len(sanitized) < 3:
        return []

    url = "https://api.openalex.org/works"
    params = {
        "filter": f"title_and_abstract.search:{sanitized}",
        "sort": "cited_by_count:desc",
        "per_page": limit,
    }

    try:
        resp = _sync_client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json().get("results", [])
        return [_format_openalex_work(w) for w in data]
    except Exception as e:
        print(f"[paper_search] foundational search failed for '{sanitized}': {type(e).__name__}")
        return []


def fetch_referenced_work_ids(openalex_id: str, limit: int = 25) -> list[str]:
    if not openalex_id:
        return []

    try:
        resp = _sync_client.get(
            f"https://api.openalex.org/works/{openalex_id}",
            params={"select": "referenced_works"},
        )
        resp.raise_for_status()

        refs = resp.json().get("referenced_works", []) or []
        ids = []

        for r in refs:
            wid = _extract_openalex_wid(r)
            if wid and wid not in ids:
                ids.append(wid)

            if len(ids) >= limit:
                break

        return ids

    except Exception:
        return []


def fetch_openalex_works_by_ids(openalex_ids: list[str], limit: int = 50) -> list[dict]:
    ids = [i for i in dict.fromkeys(openalex_ids) if i][:limit]
    if not ids:
        return []

    url = "https://api.openalex.org/works"
    params = {
        "filter": "openalex_id:" + "|".join(ids),
        "per_page": limit,
    }

    try:
        resp = _sync_client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json().get("results", [])
        return [_format_openalex_work(w) for w in data]
    except Exception:
        return []


def fetch_openalex_citation_graph(openalex_ids: list[str], limit_per_paper: int = 3) -> list[dict]:
    papers = []

    for oid in openalex_ids:
        if not oid:
            continue

        try:
            resp = _sync_client.get(f"https://api.openalex.org/works/{oid}")
            if resp.status_code != 200:
                continue

            work = resp.json()
            ref_ids = work.get("referenced_works", [])[:limit_per_paper]

            for ref_id in ref_ids:
                wid = _extract_openalex_wid(ref_id)
                if not wid:
                    continue

                r = _sync_client.get(f"https://api.openalex.org/works/{wid}")
                if r.status_code == 200:
                    papers.append(_format_openalex_work(r.json()))

            cited_url = work.get("cited_by_api_url")
            if cited_url:
                r = _sync_client.get(cited_url, params={"per_page": limit_per_paper})
                if r.status_code == 200:
                    for w in r.json().get("results", []):
                        papers.append(_format_openalex_work(w))

        except Exception:
            continue

    return papers


async def search_arxiv_async(query: str, max_results: int | None = None) -> list[dict]:
    return await asyncio.to_thread(search_arxiv, query, max_results)


async def search_openalex_async(query: str, limit: int = 10, sort_by_citations: bool = False) -> list[dict]:
    url = "https://api.openalex.org/works"
    params = {"search": query, "per_page": limit}

    if sort_by_citations:
        params["sort"] = "cited_by_count:desc"

    try:
        client = _get_async_client()
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json().get("results", [])
        return [_format_openalex_work(w) for w in data]
    except Exception:
        return []


async def search_openalex_foundational_async(query: str, limit: int = 10) -> list[dict]:
    sanitized = sanitize_openalex_search(query, max_words=8)
    if not sanitized or len(sanitized) < 3:
        return []

    url = "https://api.openalex.org/works"
    params = {
        "filter": f"title_and_abstract.search:{sanitized}",
        "sort": "cited_by_count:desc",
        "per_page": limit,
    }

    try:
        client = _get_async_client()
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json().get("results", [])
        return [_format_openalex_work(w) for w in data]
    except Exception as e:
        print(f"[paper_search] async foundational search failed for '{sanitized}': {type(e).__name__}")
        return []


async def fetch_referenced_work_ids_async(openalex_id: str, limit: int = 25) -> list[str]:
    if not openalex_id:
        return []

    try:
        client = _get_async_client()
        resp = await client.get(
            f"https://api.openalex.org/works/{openalex_id}",
            params={"select": "referenced_works"},
        )
        resp.raise_for_status()

        refs = resp.json().get("referenced_works", []) or []
        ids = []

        for r in refs:
            wid = _extract_openalex_wid(r)
            if wid and wid not in ids:
                ids.append(wid)

            if len(ids) >= limit:
                break

        return ids

    except Exception:
        return []


async def fetch_openalex_works_by_ids_async(openalex_ids: list[str], limit: int = 50) -> list[dict]:
    ids = [i for i in dict.fromkeys(openalex_ids) if i][:limit]
    if not ids:
        return []

    url = "https://api.openalex.org/works"
    params = {
        "filter": "openalex_id:" + "|".join(ids),
        "per_page": limit,
    }

    try:
        client = _get_async_client()
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json().get("results", [])
        return [_format_openalex_work(w) for w in data]
    except Exception:
        return []


async def fetch_openalex_citation_graph_async(openalex_ids: list[str], limit_per_paper: int = 3) -> list[dict]:
    papers: list[dict] = []

    for oid in openalex_ids:
        if not oid:
            continue

        try:
            client = _get_async_client()
            resp = await client.get(f"https://api.openalex.org/works/{oid}")
            if resp.status_code != 200:
                continue

            work = resp.json()
            ref_ids = work.get("referenced_works", [])[:limit_per_paper]

            for ref_id in ref_ids:
                wid = _extract_openalex_wid(ref_id)
                if not wid:
                    continue

                r = await client.get(f"https://api.openalex.org/works/{wid}")
                if r.status_code == 200:
                    papers.append(_format_openalex_work(r.json()))

            cited_url = work.get("cited_by_api_url")
            if cited_url:
                r = await client.get(cited_url, params={"per_page": limit_per_paper})
                if r.status_code == 200:
                    for w in r.json().get("results", []):
                        papers.append(_format_openalex_work(w))

        except Exception:
            continue

    return papers