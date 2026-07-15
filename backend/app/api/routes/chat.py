import time
import uuid

from fastapi import APIRouter, HTTPException
from langchain_core.messages import SystemMessage, HumanMessage

from app.models.schemas import ChatRequest, ChatResponse, PaperResult
from app.agents.graph import research_graph
from app.services.vector_store import vector_store
from app.services.graph_store import graph_store
from app.services.llm_client import get_llm
from app.services.structured_answer import get_followup_answer
from app.services.embeddings import embed_texts, similarity

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())

    if req.upload_mode == "grounded_only":
        return _handle_uploaded_only(req, session_id)

    initial_state = {
        "query": req.query,
        "session_id": session_id,
        "include_uploaded": req.include_uploaded,
        "upload_mode": req.upload_mode,
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
        "uploaded_context": [],
        "term_coverage": {},
        "papers_below_threshold": 0,
        "final_answer": "",
        "coverage_gaps": [],
        "domain_caveat": None,
        "citations": [],
        "needs_retry": False,
        "error": None,
        "validation_results": [],
        "graph_contradictions": [],
        "graph_entities": [],
    }

    t0 = time.time()
    final_state = research_graph.invoke(initial_state)
    elapsed = round(time.time() - t0, 1)

    print(f"[timing] {elapsed}s | query='{req.query}'")

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
        graph_contradictions=final_state.get("graph_contradictions", []),
        graph_entities=final_state.get("graph_entities", []),
    )


def _handle_uploaded_only(req: ChatRequest, session_id: str) -> ChatResponse:
    results = vector_store.query_session(req.query, session_id, n_results=20)
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]

    if not documents:
        raise HTTPException(
            status_code=404,
            detail="No uploaded PDFs found for this session. Upload a PDF via /api/upload first."
        )

    question_vec = embed_texts([req.query])[0]
    doc_vecs = embed_texts(documents)
    sims = [similarity(question_vec, dv) for dv in doc_vecs]
    max_sim = max(sims) if sims else 0

    is_generic_query = any(
        word in req.query.lower()
        for word in ["explain", "this paper", "summarize", "what is", "tell me about"]
    )
    if max_sim < 0.15 and not is_generic_query:
        return ChatResponse(
            answer="The uploaded PDFs do not appear to contain information relevant to your question. Please rephrase or upload a different document.",
            session_id=session_id,
            papers=[],
            citations=[],
            coverage_gaps=["Uploaded PDFs don't cover this question"],
            domain_caveat=None,
        )

    parts = []
    total_chars = 0
    max_total_chars = 6000
    for doc, meta in zip(documents, metadatas):
        if total_chars >= max_total_chars:
            break
        chunk = doc[:800]
        page_info = f" - Page {meta.get('chunk_index', '?')}" if meta.get('chunk_index') else ""
        parts.append(f"[{meta['title']}{page_info}]: {chunk}")
        total_chars += len(chunk) + 50

    context_block = "\n\n".join(parts)

    llm = get_llm(temperature=0.0)

    prompt = f"""Answer using ONLY the excerpts below.

If they lack enough information, set grounded=false and say: "The uploaded document does not provide enough information to answer this question."

Question: {req.query}

Excerpts:
{context_block}
"""
    messages = [
        SystemMessage(content="You MUST respond with valid JSON only. Never quote the excerpts. Never reproduce the document. Never output equations or markdown. Use the FollowupAnswer function."),
        HumanMessage(content=prompt),
    ]

    fallback_sources = list({meta["title"] for meta in metadatas})
    result = get_followup_answer(llm, messages, req.query, context_block, fallback_sources)

    if not result.grounded:
        return ChatResponse(
            answer=result.answer,
            session_id=session_id,
            papers=[],
            citations=[],
            coverage_gaps=["Uploaded PDFs don't fully cover this question"],
            domain_caveat=None,
        )

    paper_titles = list({meta["title"] for meta in metadatas})
    for title in paper_titles:
        meta = next((m for m in metadatas if m["title"] == title), None)
        if meta:
            graph_store.upsert_paper({
                "title": title,
                "link": meta["link"],
                "summary": documents[0][:500],
                "source": "user_upload",
                "published": "",
                "authors": [],
            }, session_id)

    papers = [
        PaperResult(title=t, authors=[], summary="", link=next((m["link"] for m in metadatas if m["title"] == t), ""), published=None)
        for t in paper_titles
    ]

    return ChatResponse(
        answer=result.answer,
        session_id=session_id,
        papers=papers,
        citations=result.sources_used,
        coverage_gaps=[],
        domain_caveat=None,
    )
