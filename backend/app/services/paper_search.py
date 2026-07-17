import arxiv
import httpx
import re
from app.config import settings

def _normalize_link(url: str) -> str:
    return url.replace("http://", "https://", 1) if url.startswith("http://") else url

def _extract_arxiv_id(link: str) -> str:
    if not link: return ""
    match = re.search(r'(\d{4}\.\d{4,5})(v\d+)?', link)
    return match.group(1) if match else ""

def _extract_openalex_id(link: str) -> str:
    if not link: return ""
    match = re.search(r'openalex\.org/(W\d+)', link)
    return match.group(1) if match else ""

def _reconstruct_abstract(inverted_index: dict | None) -> str:
    if not inverted_index: return ""
    positions = {}
    for word, idxs in inverted_index.items():
        for i in idxs: positions[i] = word
    return " ".join(positions[i] for i in sorted(positions))

def _format_openalex_work(w: dict) -> dict:
    oa = w.get("open_access") or {}
    return {
        "title": w.get("title") or "",
        "authors": [a["author"]["display_name"] for a in w.get("authorships", [])],
        "summary": _reconstruct_abstract(w.get("abstract_inverted_index")),
        "link": w.get("id", ""),
        "pdf_url": _normalize_link(oa.get("oa_url") or ""),
        "published": str(w.get("publication_year", "")),
        "citation_count": w.get("cited_by_count", 0),
        "source": "openalex",
        "openalex_id": _extract_openalex_id(w.get("id", "")),
        "arxiv_id": ""
    }

def search_arxiv(query: str) -> list[dict]:
    try:
        search = arxiv.Search(query=query, max_results=settings.ARXIV_MAX_RESULTS, sort_by=arxiv.SortCriterion.Relevance)
        results = []
        for r in search.results():
            link = _normalize_link(r.entry_id)
            results.append({
                "title": r.title, "authors": [a.name for a in r.authors], "summary": r.summary,
                "link": link, "pdf_url": _normalize_link(r.pdf_url), "published": str(r.published.date()),
                "citation_count": 0, "source": "arxiv",
                "arxiv_id": _extract_arxiv_id(link), "openalex_id": ""
            })
        return results
    except Exception:
        return []

def search_openalex(query: str, limit: int = 10, sort_by_citations: bool = False) -> list[dict]:
    url = "https://api.openalex.org/works"
    params = {"search": query, "per_page": limit}
    if sort_by_citations: params["sort"] = "cited_by_count:desc"
    try:
        resp = httpx.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json().get("results", [])
        return [_format_openalex_work(w) for w in data]
    except (httpx.HTTPError, httpx.TimeoutException):
        return []

def fetch_openalex_citation_graph(openalex_ids: list[str], limit_per_paper: int = 3) -> list[dict]:
    """Fetches papers cited by and citing the given OpenAlex IDs."""
    papers = []
    for oid in openalex_ids:
        if not oid: continue
        try:
            resp = httpx.get(f"https://api.openalex.org/works/{oid}", timeout=10)
            if resp.status_code != 200: continue
            work = resp.json()

            # Referenced works (papers this paper cites)
            ref_ids = work.get("referenced_works", [])[:limit_per_paper]
            for ref_id in ref_ids:
                r = httpx.get(f"https://api.openalex.org/works/{ref_id}", timeout=10)
                if r.status_code == 200:
                    papers.append(_format_openalex_work(r.json()))

            # Cited by (papers that cite this paper)
            cited_url = work.get("cited_by_api_url")
            if cited_url:
                r = httpx.get(cited_url, params={"per_page": limit_per_paper}, timeout=10)
                if r.status_code == 200:
                    for w in r.json().get("results", []):
                        papers.append(_format_openalex_work(w))
        except Exception:
            continue
    return papers
