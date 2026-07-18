import time
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import SystemMessage, HumanMessage

from app.models.schemas import (
    ChatRequest, ChatResponse, PaperResult, ReferenceEntry, RegenerateRequest,
    FollowupRequest, FollowupResponse,
)
from app.agents.graph import research_graph
from app.agents.state import AgentState
from app.services.vector_store import vector_store
from app.services.graph_store import graph_store
from app.services.llm_client import get_llm
from app.services.structured_answer import get_followup_answer
from app.services.embeddings import embed_texts, similarity
from app.services.reference_builder import build_references, format_reference_block
from app.services import cancellation
from app.services.sse import sse_event, progress_event, stream_text_chunks
from app.utils.text_cleaning import normalize_dashes

router = APIRouter()

GROUNDED_MAX_TOTAL_CHARS = 24000
GROUNDED_MAX_CHUNK_CHARS = 2000


def _build_initial_state(req: ChatRequest, session_id: str) -> dict:
    return {
        "query": req.query,
        "session_id": session_id,
        "include_uploaded": req.include_uploaded,
        "upload_mode": req.upload_mode,
        "response_mode": req.response_mode,
        "refined_query": None,
        "search_terms": [],
        "search_queries": [],
        "query_understanding": None,
        "query_plan": None,
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
        "final_answer": "",
        "citations": [],
        "coverage_gaps": [],
        "domain_caveat": None,
        "papers_below_threshold": 0,
        "graph_contradictions": [],
        "graph_entities": [],
        "search_terms": [],
        "conversation_history": req.conversation_history,
        "low_confidence_results": False,
        "references": [],
    }


def _run_research_graph(req: ChatRequest, session_id: str) -> ChatResponse:
    initial_state = _build_initial_state(req, session_id)
    t0 = time.time()
    final_state = research_graph.invoke(initial_state)
    elapsed = round(time.time() - t0, 1)
    print(f"[timing] {elapsed}s | mode={req.response_mode} | query='{req.query}'")
    return _finalize_chat_response(req, session_id, final_state)


def _finalize_chat_response(req: ChatRequest, session_id: str, final_state: dict) -> ChatResponse:
    ranked_papers = final_state["ranked_papers"]

    papers = [
        PaperResult(
            title=p["title"],
            authors=p["authors"],
            summary=p.get("summary", ""),
            link=p["link"],
            published=p.get("published"),
            relevance_score=p.get("final_score"),
            source=p.get("source", "unknown"),
            is_uploaded=(p.get("source") == "user_upload"),
            file_url=p.get("file_url"),
        )
        for p in ranked_papers
    ]

    references = [ReferenceEntry(**r) for r in final_state.get("references", [])]

    for p in ranked_papers:
        try:
            vector_store.upsert_paper(p, session_id)
        except Exception as e:
            print(f"[chat] vector_store persistence failed for '{p.get('title', '?')}': {e}")

    return ChatResponse(
        answer=normalize_dashes(final_state.get("final_answer", "")),
        session_id=session_id,
        papers=papers,
        citations=final_state["citations"],
        coverage_gaps=final_state.get("coverage_gaps", []),
        domain_caveat=final_state.get("domain_caveat"),
        papers_below_threshold=final_state.get("papers_below_threshold", 0),
        graph_contradictions=final_state.get("graph_contradictions", []),
        graph_entities=final_state.get("graph_entities", []),
        response_mode=req.response_mode,
        references=references,
    )


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())

    if req.upload_mode == "grounded_only":
        return _handle_uploaded_only(req, session_id)

    return _run_research_graph(req, session_id)


@router.post("/chat/stream")
def chat_stream(req: ChatRequest):
    if req.upload_mode == "grounded_only":
        raise HTTPException(
            status_code=400,
            detail="Streaming isn't available for PDF-only (grounded_only) requests yet. Use /chat.",
        )

    if not req.request_id:
        raise HTTPException(status_code=400, detail="request_id is required for /chat/stream.")

    request_id = req.request_id
    session_id = req.session_id or str(uuid.uuid4())

    def event_stream():
        cancellation.register(request_id)
        try:
            if req.response_mode == "graph_research":
                graph_store.clear_session(session_id)

            state: AgentState = _build_initial_state(req, session_id)

            t0 = time.time()
            try:
                for update in research_graph.stream(state, stream_mode="updates"):
                    if cancellation.is_cancelled(request_id):
                        yield sse_event("cancelled")
                        return

                    for node_name, delta in update.items():
                        state.update(delta)
                        yield progress_event(node_name)
            except Exception as e:
                print(f"[chat_stream] graph execution failed: {type(e).__name__}: {e}")
                yield sse_event("error", message="Something went wrong while generating this answer.")
                return

            elapsed = round(time.time() - t0, 1)
            print(f"[timing] {elapsed}s | mode={req.response_mode} | query='{req.query}' | streamed")

            response = _finalize_chat_response(req, session_id, state)

            completed = yield from stream_text_chunks(
                response.answer,
                cancel_check=lambda: cancellation.is_cancelled(request_id),
            )
            if not completed:
                yield sse_event("cancelled")
                return

            yield sse_event("result", payload=response.model_dump())
        finally:
            cancellation.cleanup(request_id)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/chat/cancel/{request_id}")
def chat_cancel(request_id: str):
    found = cancellation.cancel(request_id)
    if not found:
        return {"cancelled": False}
    return {"cancelled": True}


@router.post("/chat/regenerate", response_model=ChatResponse)
def regenerate(req: RegenerateRequest):
    if req.is_followup:
        followup_req = FollowupRequest(
            session_id=req.session_id,
            question=req.query,
            response_mode=req.response_mode,
        )
        from app.api.routes.followup import followup as run_followup
        result: FollowupResponse = run_followup(followup_req)
        return ChatResponse(
            answer=result.answer,
            session_id=req.session_id,
            papers=[],
            citations=result.sources,
            response_mode=req.response_mode,
            references=result.references,
        )

    chat_req = ChatRequest(
        query=req.query,
        session_id=req.session_id,
        upload_mode=req.upload_mode,
        include_uploaded=req.include_uploaded,
        response_mode=req.response_mode,
    )
    if chat_req.upload_mode == "grounded_only":
        return _handle_uploaded_only(chat_req, req.session_id)
    return _run_research_graph(chat_req, req.session_id)


def _handle_uploaded_only(req: ChatRequest, session_id: str) -> ChatResponse:
    results = vector_store.query_session(req.query, session_id, n_results=30)
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
        for word in ("what is", "explain", "tell me about", "what are", "describe", "overview")
    )

    if max_sim > 0.4 or is_generic_query:
        print(f"[grounded] generic query detected (max_sim={max_sim:.3f}), using LLM answer")
        context_block = "\n\n".join(
            f"[{meta['title']}]: {doc}"
            for doc, meta in zip(documents, metadatas)
        )
        llm = get_llm(temperature=0.0)
        prompt = f"""Answer the user's question using ONLY the provided PDF context. If the context does not contain enough information, say so honestly.

Context:
{context_block}

Question: {req.query}
"""
        messages = [
            SystemMessage(content="Answer concisely based on the provided PDF excerpts. Use [n] citations."),
            HumanMessage(content=prompt),
        ]
        result = get_followup_answer(llm, messages, req.query, context_block, [])
    else:
        print(f"[grounded] specific query (max_sim={max_sim:.3f}), retrieving relevant excerpts")

        combined = []
        seen_titles = set()
        for i in sorted(range(len(sims)), key=lambda j: sims[j], reverse=True):
            meta = metadatas[i]
            title = meta["title"]
            if title in seen_titles:
                continue
            seen_titles.add(title)
            combined.append({
                "title": title,
                "authors": [],
                "summary": documents[i][:500],
                "link": meta.get("file_url") or meta.get("link", ""),
                "published": None,
                "source": "user_upload",
                "file_url": meta.get("file_url") or meta.get("link", ""),
            })
            if len(combined) >= 5:
                break

        sorted_docs = sorted(zip(documents, metadatas, sims), key=lambda x: x[2], reverse=True)[:5]
        top_context = "\n\n".join(
            f"[{meta['title']}]: {doc}"
            for doc, meta, _ in sorted_docs
        )
        llm = get_llm(temperature=0.0)
        prompt = f"""Answer using ONLY the PDF excerpts below. Be specific and cite the source document name.

Excerpts:
{top_context}

Question: {req.query}
"""
        messages = [
            SystemMessage(content="Answer precisely using only the provided PDF excerpts."),
            HumanMessage(content=prompt),
        ]
        result = get_followup_answer(llm, messages, req.query, top_context, [])

    paper_dicts = []
    seen_titles = set()
    for meta in metadatas:
        title = meta["title"]
        if title in seen_titles:
            continue
        seen_titles.add(title)
        paper_dicts.append({
            "title": title,
            "authors": [],
            "summary": "",
            "link": meta.get("file_url") or meta.get("link", ""),
            "published": None,
            "source": "user_upload",
            "file_url": meta.get("file_url") or meta.get("link", ""),
        })
        graph_store.upsert_paper({
            "title": title,
            "link": meta.get("file_url") or meta.get("link", ""),
            "summary": documents[0][:500],
            "source": "user_upload",
            "published": "",
            "authors": [],
        }, session_id)

    references = build_references(paper_dicts)
    answer_text = normalize_dashes(result.answer)
    if req.response_mode in ("researched", "graph_research") and references:
        answer_text = answer_text + "\n\n---\n\n**References**\n\n" + format_reference_block(references)

    papers = [
        PaperResult(
            title=p["title"], authors=[], summary="", link=p["link"], published=None,
            source="user_upload", is_uploaded=True, file_url=p["file_url"],
        )
        for p in paper_dicts
    ]

    return ChatResponse(
        answer=answer_text,
        session_id=session_id,
        papers=papers,
        citations=result.sources_used,
        coverage_gaps=[],
        domain_caveat=None,
        response_mode=req.response_mode,
        references=[ReferenceEntry(**r) for r in references],
    )
