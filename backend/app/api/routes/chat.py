import time

from fastapi import APIRouter
from app.models.schemas import ChatRequest, ChatResponse, PaperResult
from app.agents.graph import research_graph

router = APIRouter()


def eval_result_quality(papers: list[dict]) -> dict:
    scores = [p.get("final_score", 0) for p in papers if p.get("final_score") is not None]
    years = [int(p["published"][:4]) for p in papers if p.get("published")]
    links = [p["link"] for p in papers if p.get("link")]

    return {
        "score_variance_low": (max(scores) - min(scores)) < 0.15 if len(scores) > 1 else None,
        "recency_skew": (max(years) - min(years)) < 2 if len(years) > 1 else None,
        "duplicate_links": len(links) != len(set(links)) if links else None,
    }


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    initial_state = {
        "query": req.query,
        "use_uploaded_only": req.use_uploaded_only,
        "refined_query": None,
        "search_terms": [],
        "is_definitional": False,
        "search_attempts": 0,
        "max_search_attempts": 2,
        "raw_search_results": [],
        "extracted_papers": [],
        "ranked_papers": [],
        "summaries": {},
        "final_answer": "",
        "coverage_gaps": [],
        "citations": [],
        "needs_retry": False,
        "error": None,
        "validation_results": [],
    }

    t0 = time.time()
    final_state = research_graph.invoke(initial_state)
    elapsed = round(time.time() - t0, 1)

    eval_quality = eval_result_quality(final_state["ranked_papers"])

    print(f"[timing] {elapsed}s | query='{req.query}'")

    if final_state.get("validation_results"):
        print(f"[WARN] Validation: {final_state['validation_results']}")
    if eval_quality.get("score_variance_low"):
        print(f"[WARN] Score variance too low: {eval_quality}")
    if eval_quality.get("recency_skew"):
        print(f"[WARN] Recency skew detected: {eval_quality}")

    papers = [
        PaperResult(
            title=p["title"],
            authors=p["authors"],
            summary=p.get("summary", ""),
            link=p["link"],
            published=p.get("published"),
            relevance_score=p.get("final_score"),
        )
        for p in final_state["ranked_papers"]
    ]

    return ChatResponse(
        answer=final_state["final_answer"],
        papers=papers,
        citations=final_state["citations"],
    )
