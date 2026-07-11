import time
import uuid

from fastapi import APIRouter, HTTPException
from langchain_core.messages import SystemMessage, HumanMessage

from app.models.schemas import ChatRequest, ChatResponse, PaperResult
from app.agents.graph import research_graph
from app.services.vector_store import vector_store
from app.services.llm_client import get_llm
from app.services.structured_answer import get_followup_answer

router = APIRouter()


def eval_result_quality(papers: list[dict], num_concepts: int = 1) -> dict:
    scores = [p.get("final_score", 0) for p in papers if p.get("final_score") is not None]
    years = [int(p["published"][:4]) for p in papers if p.get("published")]
    links = [p["link"] for p in papers if p.get("link")]

    variance_threshold = 0.15 if num_concepts <= 1 else 0.10

    return {
        "score_variance_low": (max(scores) - min(scores)) < variance_threshold if len(scores) > 1 else None,
        "recency_skew": (max(years) - min(years)) < 2 if len(years) > 1 else None,
        "duplicate_links": len(links) != len(set(links)) if links else None,
    }


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())

    if req.use_uploaded_only:
        return _handle_uploaded_only(req, session_id)

    initial_state = {
        "query": req.query,
        "session_id": session_id,
        "use_uploaded_only": req.use_uploaded_only,
        "refined_query": None,
        "search_terms": [],
        "is_definitional": False,
        "likely_cs_relevant": True,
        "domain_full": None,
        "domain_keywords": [],
        "mandatory_domain_keywords": None,
        "search_attempts": 0,
        "max_search_attempts": 2,
        "raw_search_results": [],
        "extracted_papers": [],
        "ranked_papers": [],
        "summaries": {},
        "term_coverage": {},
        "papers_below_threshold": 0,
        "final_answer": "",
        "coverage_gaps": [],
        "domain_caveat": None,
        "citations": [],
        "needs_retry": False,
        "error": None,
        "validation_results": [],
    }

    t0 = time.time()
    final_state = research_graph.invoke(initial_state)
    elapsed = round(time.time() - t0, 1)

    eval_quality = eval_result_quality(final_state["ranked_papers"], num_concepts=len(final_state.get("search_terms", [1])))

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
        session_id=session_id,
        papers=papers,
        citations=final_state["citations"],
        coverage_gaps=final_state.get("coverage_gaps", []),
        domain_caveat=final_state.get("domain_caveat"),
        papers_below_threshold=final_state.get("papers_below_threshold", 0),
    )


def _handle_uploaded_only(req: ChatRequest, session_id: str) -> ChatResponse:
    results = vector_store.query_session(req.query, session_id, n_results=5)
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]

    if not documents:
        raise HTTPException(
            status_code=404,
            detail="No uploaded PDFs found for this session. Upload a PDF via /api/upload first."
        )

    context_block = "\n\n".join(
        f"[{meta['title']}]: {doc}"
        for doc, meta in zip(documents, metadatas)
    )

    llm = get_llm(temperature=0.2)

    prompt = f"""Answer the question using ONLY the uploaded PDF excerpts below.

If the excerpts don't actually contain enough information to answer, set grounded=false
and say so honestly in the answer field rather than guessing.

Question: {req.query}

Uploaded excerpts:
{context_block}
"""
    messages = [
        SystemMessage(content="Answer using the FollowupAnswer function. Return a valid function call only."),
        HumanMessage(content=prompt),
    ]

    fallback_sources = list({meta["title"] for meta in metadatas})
    result = get_followup_answer(llm, messages, req.query, context_block, fallback_sources)

    paper_titles = list({meta["title"] for meta in metadatas})
    papers = [
        PaperResult(title=t, authors=[], summary="", link=f"uploaded://{t}", published=None)
        for t in paper_titles
    ]

    return ChatResponse(
        answer=result.answer,
        session_id=session_id,
        papers=papers,
        citations=result.sources_used,
        coverage_gaps=[] if result.grounded else ["Uploaded PDFs don't fully cover this question"],
        domain_caveat=None,
    )
