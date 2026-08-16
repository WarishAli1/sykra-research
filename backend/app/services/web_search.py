import asyncio

try:
    from duckduckgo_search import DDGS 
except Exception:
    DDGS = None

_AUTHORITY_BOOSTS = {
    "clinical_medical": "(site:who.int OR site:cdc.gov OR site:nih.gov OR site:cochranelibrary.com OR site:fda.gov)",
    "technical_standards": "(site:nist.gov OR site:iso.org OR site:ietf.org OR site:w3.org OR site:ieee.org)",
    "financial_economic": "(site:sec.gov OR site:imf.org OR site:worldbank.org OR site:federalreserve.gov)",
    "legal_policy": "(site:gov OR site:europa.eu OR site:un.org OR site:supremecourt.gov)",
    "industry_market": "(site:mckinsey.com OR site:bcg.com OR site:stanford.edu OR site:mit.edu OR site:gartner.com)",
    "academic": ""
}

async def search_web_async(query: str, source_intent: str = "academic", max_results: int = 10) -> list[dict]:
    if DDGS is None:
        return []

    boost = _AUTHORITY_BOOSTS.get(source_intent, "")
    final_query = f"{query} {boost}".strip()
    def _search():
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(final_query, max_results=max_results))
                return [
                    {
                        "title": r.get("title", ""),
                        "summary": r.get("body", ""),
                        "link": r.get("href", ""),
                        "source": "web",
                        "authors": [],
                        "published": "",
                        "citation_count": 0,
                        "_is_web_doc": True,
                    }
                    for r in results
                ]
        except Exception as e:
            print(f"[web_search] failed: {e}")
            return []
            
    return await asyncio.to_thread(_search)