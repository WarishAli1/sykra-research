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
from app.services.filename_service import generate_filename
from app.services.reference_builder import filter_cited_references

router = APIRouter()

GROUNDED_MAX_TOTAL_CHARS = 24000
GROUNDED_MAX_CHUNK_CHARS = 2000


def _build_initial_state(req: ChatRequest, session_id: str, turn_id: str) -> dict:
    return {
        "query": req.query,
        "session_id": session_id,
        "turn_id": turn_id,
        "evidence_mode": req.evidence_mode,
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
        "conversation_history": req.conversation_history,
        "low_confidence_results": False,
        "references": [],
        "chart_spec_raw": None,
        "chart_url": None,
        "comparison_table_markdown": None,
        "comparison_table_caption": None,
        "needs_revision": False,
        "revision_count": 0,
        "revision_instruction": None,
    }


def _run_research_graph(req: ChatRequest, session_id: str, turn_id: str) -> ChatResponse:
    initial_state = _build_initial_state(req, session_id, turn_id)
    t0 = time.time()
    final_state = research_graph.invoke(initial_state)
    elapsed = round(time.time() - t0, 1)
    print(f"[timing] {elapsed}s | mode={req.response_mode} | query='{req.query}'")
    return _finalize_chat_response(req, session_id, turn_id, final_state)


def _finalize_chat_response(req: ChatRequest, session_id: str, turn_id: str, final_state: dict) -> ChatResponse:
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
    filename = generate_filename(
        turn_id,
        final_state.get("final_answer", "")
    )
    return ChatResponse(
        answer=normalize_dashes(final_state.get("final_answer", "")),
        session_id=session_id,
        turn_id=turn_id,
        papers=papers,
        filename=filename,
        citations=final_state["citations"],
        coverage_gaps=final_state.get("coverage_gaps", []),
        domain_caveat=final_state.get("domain_caveat"),
        papers_below_threshold=final_state.get("papers_below_threshold", 0),
        graph_contradictions=final_state.get("graph_contradictions", []),
        graph_entities=final_state.get("graph_entities", []),
        response_mode=req.response_mode,
        references=references,
        chart_url=final_state.get("chart_url"),
    )


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())
    turn_id = req.turn_id or str(uuid.uuid4())

    return _run_research_graph(req, session_id, turn_id)


@router.post("/chat/stream")
def chat_stream(req: ChatRequest):
    if not req.request_id:
        raise HTTPException(status_code=400, detail="request_id is required for /chat/stream.")

    request_id = req.request_id
    session_id = req.session_id or str(uuid.uuid4())
    turn_id = req.turn_id or str(uuid.uuid4())

    def event_stream():
        cancellation.register(request_id)
        try:
            if req.response_mode == "graph_research":
                graph_store.clear_session(session_id)

            state: AgentState = _build_initial_state(req, session_id, turn_id)

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

            response = _finalize_chat_response(req, session_id, turn_id, state)

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
    turn_id = req.turn_id or str(uuid.uuid4())

    if req.is_followup:
        followup_req = FollowupRequest(
            session_id=req.session_id,
            turn_id=turn_id,
            question=req.query,
            response_mode=req.response_mode,
        )
        from app.api.routes.followup import followup as run_followup
        result: FollowupResponse = run_followup(followup_req)
        return ChatResponse(
            answer=result.answer,
            session_id=req.session_id,
            turn_id=turn_id,
            papers=[],
            citations=result.sources,
            response_mode=req.response_mode,
            references=result.references,
            chart_url=result.chart_url,
        )

    chat_req = ChatRequest(
        query=req.query,
        session_id=req.session_id,
        turn_id=turn_id,
        evidence_mode=getattr(req, "evidence_mode", "literature"),
        response_mode=req.response_mode,
    )
    return _run_research_graph(chat_req, req.session_id, turn_id)
