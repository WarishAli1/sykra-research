from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import SystemMessage, HumanMessage

from app.models.schemas import FollowupRequest, FollowupResponse
from app.services.vector_store import vector_store
from app.services.llm_client import get_llm
from app.services.structured_answer import get_followup_answer
from app.services.embeddings import embed_texts, similarity
from app.services.reference_builder import build_references, format_reference_block
from app.services import cancellation
from app.services.sse import sse_event, stream_text_chunks
from app.utils.text_cleaning import normalize_dashes

router = APIRouter()


def _build_state(req: FollowupRequest, context_text: str):
    return {
        "query": req.question,
        "session_id": req.session_id,
        "response_mode": req.response_mode,
        "context_text": context_text,
        "final_answer": "",
    }


@router.post("/followup", response_model=FollowupResponse)
def followup(req: FollowupRequest):
    session_id = req.session_id
    question = req.question

    history = vector_store.get_session_history(session_id)

    context_text = ""
    if history.get("papers"):
        context_text = "\n\n".join(
            p.get("summary", p.get("title", ""))
            for p in history["papers"][:20]
        )

    llm = get_llm(temperature=0.0)
    messages = [
        SystemMessage(
            content="You are a helpful research assistant. Use context below to answer. "
                    "Cite sources with [n] notation. If context is insufficient, say so."
        ),
        HumanMessage(content=f"Previous conversation context:\n\n{context_text}\n\nQuestion: {question}"),
    ]

    result = get_followup_answer(llm, messages, question, context_text, history.get("papers", []))

    references = build_references(history.get("papers", []))

    answer_text = normalize_dashes(result.answer)
    if req.response_mode in ("researched", "graph_research") and references:
        answer_text = answer_text + "\n\n---\n\n**References**\n\n" + format_reference_block(references)

    return FollowupResponse(
        answer=answer_text,
        session_id=session_id,
        sources=result.sources_used,
        references=[{"title": r["title"], "url": r["link"]} for r in references],
    )


@router.post("/followup/stream")
def followup_stream(req: FollowupRequest):
    if not req.request_id:
        raise HTTPException(status_code=400, detail="request_id is required.")

    session_id = req.session_id
    question = req.question
    request_id = req.request_id

    def event_stream():
        cancellation.register(request_id)
        try:
            history = vector_store.get_session_history(session_id)

            if cancellation.is_cancelled(request_id):
                yield sse_event("cancelled")
                return

            context_text = ""
            if history.get("papers"):
                context_parts = []
                for p in history["papers"][:20]:
                    context_parts.append(p.get("summary", p.get("title", "")))
                context_text = "\n\n".join(context_parts)

            yield sse_event("progress", message="generating")

            llm = get_llm(temperature=0.0)
            messages = [
                SystemMessage(
                    content="You are a helpful research assistant. Use context below to answer. "
                            "Cite sources with [n] notation. If context is insufficient, say so."
                ),
                HumanMessage(content=f"Previous conversation context:\n\n{context_text}\n\nQuestion: {question}"),
            ]

            result = get_followup_answer(llm, messages, question, context_text, history.get("papers", []))

            if cancellation.is_cancelled(request_id):
                yield sse_event("cancelled")
                return

            references = build_references(history.get("papers", []))

            answer_text = normalize_dashes(result.answer)
            if req.response_mode in ("researched", "graph_research") and references:
                answer_text = answer_text + "\n\n---\n\n**References**\n\n" + format_reference_block(references)

            completed = yield from stream_text_chunks(
                answer_text,
                cancel_check=lambda: cancellation.is_cancelled(request_id),
            )
            if not completed:
                yield sse_event("cancelled")
                return

            yield sse_event("result", payload={
                "answer": answer_text,
                "session_id": session_id,
                "sources": result.sources_used,
                "references": [{"title": r["title"], "url": r["link"]} for r in references],
            })
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


@router.post("/followup/cancel/{request_id}")
def followup_cancel(request_id: str):
    found = cancellation.cancel(request_id)
    if not found:
        return {"cancelled": False}
    return {"cancelled": True}
