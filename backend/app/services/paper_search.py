import asyncio
import re

import xml.etree.ElementTree as ET
import httpx

from app.config import settings

_STOP_WORDS = {
    "what", "is", "are", "was", "were", "a", "an", "the", "how", "does", "do",
    "why", "when", "which", "who", "whom", "of", "in", "on", "for", "to",
    "and", "or", "with", "by", "from", "as", "at", "be", "this", "that",
    "these", "those", "explain", "define", "describe", "overview",
    "introduction", "meaning", "works", "work", "used", "use",
}

_ARXIV_API = "https://export.arxiv.org/api/query"
_ATOM = "{http://www.w3.org/2005/Atom}"

_LIMITS = httpx.Limits(
    max_keepalive_connections=20,
    max_connections=100,
)

_sync_client = httpx.Client(
    timeout=7,
    limits=_LIMITS,
)

_async_client: httpx.AsyncClient | None = None


def _log_http_error(context: str, exc: Exception, query: str = "") -> None:
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        url = str(exc.request.url)
        try:
            body = exc.response.text[:200]
        except Exception:
            body = ""
        print(
            f"[paper_search] {context} failed: "
            f"status={status} url={url} query={query!r} body={body}"
        )
    else:
        print(
            f"[paper_search] {context} failed: "
            f"{type(exc).__name__}: {exc} query={query!r}"
        )


def _clean_arxiv_query(query: str) -> str:
    q = re.sub(r"[\(\)\[\]]", " ", query or "")
    q = re.sub(r"\s+", " ", q).strip()
    words = [w for w in q.split() if w][:10]
    return " ".join(words)


def _get_async_client() -> httpx.AsyncClient:
    global _async_client
    if _async_client is None:
        _async_client = httpx.AsyncClient(
            timeout=7,
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


def _extract_doi(raw: str) -> str:
    if not raw:
        return ""
    raw = raw.strip()
    raw = raw.replace("https://doi.org/", "").replace("http://doi.org/", "")
    return raw


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
    ids = w.get("ids") or {}
    authors = []

    for a in w.get("authorships", []):
        author = a.get("author") or {}
        name = author.get("display_name")
        if name:
            authors.append(name)

    concepts = []
    for c in (w.get("concepts") or [])[:8]:
        name = c.get("display_name") if isinstance(c, dict) else None
        if name:
            concepts.append(name)

    venue = ""
    primary_location = w.get("primary_location") or {}
    src = (primary_location.get("source") or {}) if isinstance(primary_location, dict) else {}
    if isinstance(src, dict):
        venue = src.get("display_name") or ""

    doi = _extract_doi(ids.get("doi") or w.get("doi") or "")
    arxiv_id = _extract_arxiv_id(ids.get("arxiv") or "")

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
        "arxiv_id": arxiv_id,
        "doi": doi,
        "venue": venue,
        "keywords": concepts,
    }


def sanitize_openalex_search(text: str, max_words: int = 8) -> str:
    text = re.sub(r"[^\w\s+#.-]", " ", text or "")
    words = [w for w in text.lower().split() if w]
    kept = [w for w in words if w not in _STOP_WORDS]
    if not kept:
        kept = words
    return " ".join(kept[:max_words]).strip()


def search_arxiv(query: str, max_results: int | None = None) -> list[dict]:
    q = _clean_arxiv_query(query)
    if not q:
        return []

    return _arxiv_search(f"all:{q}", max_results)



def _arxiv_search(search_query: str, max_results: int | None = None) -> list[dict]:
    params = {
        "search_query": search_query,
        "start": 0,
        "max_results": max_results or settings.ARXIV_MAX_RESULTS,
        "sortBy": "relevance",
        "sortOrder": "descending",
    }

    try:
        resp = _sync_client.get(_ARXIV_API, params=params, timeout=6)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
    except Exception:
        return []

    results = []
    for entry in root.findall(f"{_ATOM}entry"):
        title = re.sub(r"\s+", " ", (entry.findtext(f"{_ATOM}title") or "").strip())
        summary = re.sub(r"\s+", " ", (entry.findtext(f"{_ATOM}summary") or "").strip())
        link = _normalize_link((entry.findtext(f"{_ATOM}id") or "").strip())
        published = (entry.findtext(f"{_ATOM}published") or "")[:10]

        authors = [
            (a.findtext(f"{_ATOM}name") or "").strip()
            for a in entry.findall(f"{_ATOM}author")
            if (a.findtext(f"{_ATOM}name") or "").strip()
        ]

        pdf = ""
        for el in entry.findall(f"{_ATOM}link"):
            if el.get("title") == "pdf":
                pdf = _normalize_link(el.get("href", ""))

        if not title:
            continue

        results.append({
            "title": title,
            "authors": authors,
            "summary": summary,
            "link": link,
            "pdf_url": pdf or link,
            "published": published,
            "citation_count": 0,
            "source": "arxiv",
            "arxiv_id": _extract_arxiv_id(link),
            "openalex_id": "",
            "doi": "",
            "venue": "arxiv",
            "keywords": [],
        })

    return results


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




def search_openalex_by_title(title: str, limit: int = 5) -> list[dict]:
    t = (title or "").strip()
    if not t:
        return []
    url = "https://api.openalex.org/works"
    params = {
        "filter": f"title.search:{t}",
        "per_page": limit,
        "sort": "cited_by_count:desc",
    }
    try:
        resp = _sync_client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json().get("results", [])
        return [_format_openalex_work(w) for w in data]
    except Exception as e:
        print(f"[paper_search] title search failed for '{t}': {type(e).__name__}")
        return []


def _format_semantic_scholar_paper(p: dict) -> dict:
    authors = [a.get("name") or "" for a in p.get("authors", []) if a.get("name")]
    ext = p.get("externalIds") or {}
    arxiv_id = _extract_arxiv_id(ext.get("ArXiv") or "")
    pdf_url = ""
    oapdf = p.get("openAccessPdf") or {}
    if isinstance(oapdf, dict):
        pdf_url = _normalize_link(oapdf.get("url") or "")
    doi = _extract_doi(ext.get("DOI") or "")
    paper_id = p.get("paperId") or ""
    link = ""
    if arxiv_id:
        link = f"https://arxiv.org/abs/{arxiv_id}"
    elif doi:
        link = f"https://doi.org/{doi}"
    elif paper_id:
        link = f"https://www.semanticscholar.org/paper/{paper_id}"
    return {
        "title": p.get("title") or "",
        "authors": authors,
        "summary": p.get("abstract") or "",
        "link": link,
        "pdf_url": pdf_url,
        "published": str(p.get("year") or ""),
        "citation_count": p.get("citationCount") or 0,
        "influential_citation_count": p.get("influentialCitationCount", 0) or 0,
        "source": "semanticscholar",
        "openalex_id": "",
        "arxiv_id": arxiv_id,
        "doi": doi,
        "venue": "",
        "keywords": [],
    }


def search_semantic_scholar(
    query: str,
    limit: int = 10,
    sort_by_citations: bool = False,
) -> list[dict]:
    q = (query or "").strip().replace('"', "")
    if not q:
        return []
    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    params = {
        "query": q,
        "limit": min(limit, 100),
        "fields": (
            "title,authors,year,externalIds,citationCount,"
            "influentialCitationCount,abstract,openAccessPdf"
        ),
    }
    if sort_by_citations:
        params["sort"] = "citationCount:desc"
    try:
        resp = _sync_client.get(url, params=params)
        if resp.status_code == 429:
            return []
        resp.raise_for_status()
        data = resp.json().get("data", [])
        return [_format_semantic_scholar_paper(w) for w in data]
    except Exception:
        return []


def search_openalex_foundational(query: str, limit: int = 10) -> list[dict]:
    sanitized = sanitize_openalex_search(query, max_words=8)
    if not sanitized or len(sanitized) < 3:
        return []

    url = "https://api.openalex.org/works"
    params = {
        "search": sanitized,
        "sort": "cited_by_count:desc",
        "per_page": limit,
    }

    try:
        resp = _sync_client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json().get("results", [])
        return [_format_openalex_work(w) for w in data]
    except Exception as e:
        _log_http_error("foundational search", e, sanitized)
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


def _normalize_search_text(text: str) -> str:
    """
    Normalize unicode punctuation variants that commonly appear in
    LLM-generated titles/queries but break exact-match search APIs --
    e.g. non-breaking hyphen (U+2011), en/em dashes, curly quotes,
    non-breaking spaces. Without this, a query like 'scaled dot‑product
    attention' (with U+2011) can silently fail to match arXiv's stored
    title 'scaled dot-product attention' (with a plain ASCII hyphen).
    """
    if not text:
        return ""

    replacements = {
        "\u2011": "-",  
        "\u2010": "-",  
        "\u2012": "-",  
        "\u2013": "-",  
        "\u2014": "-",
        "\u2018": "'",  
        "\u2019": "'",  
        "\u201c": '"',  
        "\u201d": '"',  
        "\u00a0": " ",   
    }

    for src, dst in replacements.items():
        text = text.replace(src, dst)

    return text


def _run_arxiv_title_query(search_query: str, max_results: int) -> list[dict]:
    params = {
        "search_query": search_query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "relevance",
        "sortOrder": "descending",
    }

    try:
        resp = _sync_client.get(_ARXIV_API, params=params, timeout=6)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
    except Exception:
        return []

    results = []
    for entry in root.findall(f"{_ATOM}entry"):
        title_text = re.sub(r"\s+", " ", (entry.findtext(f"{_ATOM}title") or "").strip())
        summary = re.sub(r"\s+", " ", (entry.findtext(f"{_ATOM}summary") or "").strip())
        link = _normalize_link((entry.findtext(f"{_ATOM}id") or "").strip())
        published = (entry.findtext(f"{_ATOM}published") or "")[:10]

        authors = [
            (a.findtext(f"{_ATOM}name") or "").strip()
            for a in entry.findall(f"{_ATOM}author")
            if (a.findtext(f"{_ATOM}name") or "").strip()
        ]

        pdf = ""
        for el in entry.findall(f"{_ATOM}link"):
            if el.get("title") == "pdf":
                pdf = _normalize_link(el.get("href", ""))

        if not title_text:
            continue

        results.append({
            "title": title_text,
            "authors": authors,
            "summary": summary,
            "link": link,
            "pdf_url": pdf or link,
            "published": published,
            "citation_count": 0,
            "source": "arxiv",
            "arxiv_id": _extract_arxiv_id(link),
            "openalex_id": "",
            "doi": "",
            "venue": "arxiv",
            "keywords": [],
        })

    return results


def search_arxiv_by_title(title: str, max_results: int | None = None) -> list[dict]:
    clean = re.sub(r'["\'“”]+', "", _normalize_search_text(title) or "").strip()
    if not clean:
        return []

    n_results = max_results or settings.ARXIV_MAX_RESULTS

    results = _run_arxiv_title_query(f'ti:"{clean}"', n_results)

    if results:
        return results

    words = [w for w in re.split(r"\s+", clean) if len(w) > 2]

    if not words:
        return []

    relaxed_query = " AND ".join(f'ti:{w}' for w in words[:8])
    fuzzy_results = _run_arxiv_title_query(relaxed_query, n_results)

    if fuzzy_results:
        print(
            f"[paper_search] arxiv exact title match failed for '{clean[:80]}', "
            f"used relaxed word-match fallback ({len(fuzzy_results)} results)"
        )

    return fuzzy_results



def _format_semantic_scholar_work(w: dict) -> dict:
    authors = []
    for a in w.get("authors") or []:
        name = a.get("name")
        if name:
            authors.append(name)

    pdf = (w.get("openAccessPdf") or {}).get("url") or ""
    external = w.get("externalIds") or {}
    doi = _extract_doi(external.get("DOI") or "")
    arxiv_id = _extract_arxiv_id(external.get("ArXiv") or "")

    return {
        "title": w.get("title") or "",
        "authors": authors,
        "summary": (w.get("abstract") or "").strip(),
        "link": _normalize_link(f"https://www.semanticscholar.org/paper/{w.get('paperId', '')}")
        if w.get("paperId")
        else "",
        "pdf_url": _normalize_link(pdf),
        "published": str(w.get("year") or ""),
        "citation_count": w.get("citationCount", 0) or 0,
        "influential_citation_count": w.get("influentialCitationCount", 0) or 0,      
        "source": "semantic_scholar",
        "arxiv_id": arxiv_id,
        "openalex_id": "",
        "doi": doi,
        "venue": "",
        "keywords": [],
    }


async def search_arxiv_by_title_async(title: str, max_results: int | None = None) -> list[dict]:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(search_arxiv_by_title, title, max_results),
            timeout=4.0,
        )
    except asyncio.TimeoutError:
        print(f"[paper_search] arxiv title search timed out for '{title[:80]}'")
        return []
    except Exception:
        return []


async def search_semantic_scholar_async(
    query: str,
    limit: int = 10,
    sort_by_citations: bool = False,
) -> list[dict]:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                search_semantic_scholar, query, limit, sort_by_citations
            ),
            timeout=4.0,
        )
    except asyncio.TimeoutError:
        print(f"[paper_search] semantic scholar search timed out for '{query[:80]}'")
        return []
    except Exception:
        return []


async def search_arxiv_async(query: str, max_results: int | None = None) -> list[dict]:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(search_arxiv, query, max_results),
            timeout=4.0,
        )
    except asyncio.TimeoutError:
        print(f"[paper_search] arxiv search timed out for '{query[:80]}'")
        return []
    except Exception:
        return []



async def search_openalex_by_title_async(title: str, limit: int = 5) -> list[dict]:
    title = _normalize_search_text(title)

    url = "https://api.openalex.org/works"
    params = {
        "filter": f"title.search:{title}",
        "per_page": limit,
        "sort": "cited_by_count:desc",
    }

    try:
        client = _get_async_client()
        resp = await asyncio.wait_for(
            client.get(url, params=params),
            timeout=4.0,
        )
        resp.raise_for_status()
        data = resp.json().get("results", [])
        return [_format_openalex_work(w) for w in data]
    except asyncio.TimeoutError:
        print(f"[paper_search] openalex title search timed out for '{title[:80]}'")
        return []
    except Exception:
        return []

async def search_openalex_async(
    query: str,
    limit: int = 10,
    sort_by_citations: bool = False,
    min_year: int | None = None,
    max_year: int | None = None,
) -> list[dict]:
    url = "https://api.openalex.org/works"
    params = {"search": query, "per_page": limit}
    if sort_by_citations:
        params["sort"] = "cited_by_count:desc"


    if min_year and max_year:
        params["filter"] = f"publication_year:{min_year}-{max_year}"
    elif min_year:
        params["filter"] = f"publication_year:{min_year}-"
    elif max_year:
        params["filter"] = f"publication_year:-{max_year}"


    try:
        client = _get_async_client()
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json().get("results", [])
        return [_format_openalex_work(w) for w in data]
    except Exception:
        return []


async def search_openalex_foundational_async(
    query: str,
    limit: int = 10,
    min_year: int | None = None,
    max_year: int | None = None,
) -> list[dict]:
    sanitized = sanitize_openalex_search(query, max_words=8)
    if not sanitized or len(sanitized) < 3:
        return []
    url = "https://api.openalex.org/works"
    params = {
        "search": sanitized,
        "sort": "cited_by_count:desc",
        "per_page": limit,
    }


    if min_year and max_year:
        params["filter"] = f"publication_year:{min_year}-{max_year}"
    elif min_year:
        params["filter"] = f"publication_year:{min_year}-"
    elif max_year:
        params["filter"] = f"publication_year:-{max_year}"


    try:
        client = _get_async_client()
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json().get("results", [])
        return [_format_openalex_work(w) for w in data]
    except Exception as e:
        _log_http_error("async foundational search", e, sanitized)
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