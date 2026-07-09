import arxiv
import httpx
import re
from app.config import settings


def _normalize_link(url: str) -> str:
    return url.replace("http://", "https://", 1) if url.startswith("http://") else url


def _reconstruct_abstract(inverted_index: dict | None) -> str:
    if not inverted_index:
        return ""
    positions = {}
    for word, idxs in inverted_index.items():
        for i in idxs:
            positions[i] = word
    return " ".join(positions[i] for i in sorted(positions))


def search_arxiv(query: str) -> list[dict]:
    try:
        search = arxiv.Search(
            query=query,
            max_results=settings.ARXIV_MAX_RESULTS,
            sort_by=arxiv.SortCriterion.Relevance
        )
        results = []
        for r in search.results():
            results.append({
                "title": r.title,
                "authors": [a.name for a in r.authors],
                "summary": r.summary,
                "link": _normalize_link(r.entry_id),
                "pdf_url": _normalize_link(r.pdf_url),
                "published": str(r.published.date()),
                "citation_count": 0,
                "source": "arxiv",
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
        resp = httpx.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json().get("results", [])
    except (httpx.HTTPError, httpx.TimeoutException):
        return []

    results = []
    for w in data:
        oa = w.get("open_access") or {}
        results.append({
            "title": w.get("title") or "",
            "authors": [a["author"]["display_name"] for a in w.get("authorships", [])],
            "summary": _reconstruct_abstract(w.get("abstract_inverted_index")),
            "link": w.get("id", ""),
            "pdf_url": _normalize_link(oa.get("oa_url") or ""),
            "published": str(w.get("publication_year", "")),
            "citation_count": w.get("cited_by_count", 0),
            "source": "openalex",
        })
    return results
