import arxiv
from app.config import settings

def search_arxiv(query: str) -> list[dict]:
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
            "link": r.entry_id,
            "pdf_url": r.pdf_url,
            "published": str(r.published.date())
        })
    return results
