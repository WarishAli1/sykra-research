import asyncio
from app.agents.state import AgentState
from app.services.pdf_reader import extract_all
from app.services.llm_client import get_llm


def fetch_pdf_node(state: AgentState) -> AgentState:
    papers = state["ranked_papers"]
    pdf_urls = [p["pdf_url"] for p in papers]

    llm = get_llm(temperature=0)
    extracted = asyncio.run(extract_all(pdf_urls, llm=llm))

    extracted_by_url = {e["url"]: e for e in extracted}
    merged = []
    for p in papers:
        ext = extracted_by_url.get(p["pdf_url"], {})
        if ext.get("extraction_method") == "failed" or not ext.get("text"):
            merged.append({**p, "text": p.get("summary", ""), "extraction_method": "abstract_only"})
        else:
            merged.append({**p, **ext})

    return {**state, "ranked_papers": merged}
