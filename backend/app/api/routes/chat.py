import asyncio
import datetime
import time
import uuid
import json
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.models.schemas import (
    ChatRequest,
    ChatResponse,
    PaperResult,
    ReferenceEntry,
    RegenerateRequest,
    FollowupRequest,
    FollowupResponse,
)
from app.services.previous_papers import previous_papers_from_db
from app.db.models import LibraryPaper
from app.agents.graph import research_graph, run_enrichment
from app.agents.report_modules import get_disclaimer
from app.agents.state import AgentState
from app.services.vector_store import vector_store
from app.services.graph_store import graph_store
from app.services import cancellation
from app.services.sse import (
    sse_event,
    progress_event,
    stream_text_chunks_async,
    bridge_register,
    bridge_push,
    bridge_get,
    bridge_cleanup,
    stream_section_words,
)
from app.utils.text_sanitizer import sanitize_for_web_preserving_math
from app.services.filename_service import generate_filename
from app.services.reference_builder import (
    paper_id_to_ref_id_map,
    rewrite_inline_citations,
)
from app.services.citation_grounding import ABSTAIN_TEXT
from app.services.chat_titles import schedule_title_generation
from app.services.library_store import save_papers
from app.auth import get_current_user
from app.db.database import get_db
from app.db.models import Chat, Message, ResearchSession, User
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession
from slowapi import Limiter
from slowapi.util import get_remote_address


router = APIRouter()
limiter = Limiter(key_func=get_remote_address)

_EMPTY_ANSWER_FALLBACK = (
    "I could not find enough directly supporting evidence in the available sources "
    "to answer this reliably. Please provide more context or retry."
)

def _get_or_create_chat(db: DBSession, user: User, session_id: str, query: str, requested_chat_id: str | None = None) -> Chat:
    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid session identifier.") from exc
    research_session = db.scalar(select(ResearchSession).where(ResearchSession.id == session_uuid, ResearchSession.user_id == user.id))
    if not research_session:
        raise HTTPException(status_code=404, detail="Session not found.")
    if requested_chat_id:
        try:
            chat_uuid = uuid.UUID(requested_chat_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid chat identifier.") from exc
        chat = db.scalar(select(Chat).where(Chat.id == chat_uuid, Chat.session_id == session_uuid, Chat.user_id == user.id, Chat.deleted_at.is_(None)))
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found.")
        return chat
    chat = Chat(id=uuid.uuid4(), session_id=session_uuid, user_id=user.id, title="New chat")
    db.add(chat)
    db.flush()
    return chat


def _persist_message(db: DBSession, chat: Chat, role: str, content: str, citations: dict | None = None, status: str = "complete") -> None:
    now = datetime.datetime.now(datetime.timezone.utc)
    chat.updated_at = now
    if chat.research_session:
        chat.research_session.updated_at = now
    db.add(Message(chat_id=chat.id, role=role, content=content, citations=citations or {}, status=status))
    db.commit()


def _create_message(
    db: DBSession,
    chat: Chat,
    role: str,
    content: str = "",
    citations: dict | None = None,
    status: str = "streaming",
) -> Message:
    now = datetime.datetime.now(datetime.timezone.utc)
    chat.updated_at = now
    if chat.research_session:
        chat.research_session.updated_at = now
    message = Message(
        chat_id=chat.id,
        role=role,
        content=content,
        citations=citations or {},
        status=status,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def _update_message(
    db: DBSession,
    message: Message,
    content: str,
    *,
    status: str | None = None,
    citations: dict | None = None,
) -> None:
    message.content = content
    if message.chat.research_session:
        message.chat.research_session.updated_at = datetime.datetime.now(datetime.timezone.utc)
    if status:
        message.status = status
    if citations is not None:
        message.citations = citations
    db.commit()


def _answer_meta(response_mode, evidence_mode, query, ranked):
    return {"response_mode": response_mode, "evidence_mode": evidence_mode,
            "source_query": query, "paper_links": [p["link"] for p in ranked if p.get("link")]}

def _replace_assistant_message(db, user, chat, query, content, citations):
    msgs = list(db.scalars(select(Message).where(Message.chat_id == chat.id).order_by(Message.created_at)))
    start = max((i for i, m in enumerate(msgs) if m.role == "user" and (m.content or "").strip() == query.strip()), default=None)
    old = []
    if start is not None:
        for m in msgs[start + 1:]:
            if m.role == "user":
                break
            if m.role == "assistant":
                old.append(m)
    if not old:
        _persist_message(db, chat, "assistant", content, citations)
        return
    links = lambda m: set((m.citations or {}).get("paper_links") or [])
    stale = set().union(*(links(m) for m in old))
    keep = set().union(*(links(m) for m in msgs if m.role == "assistant" and m not in old)) | set(citations.get("paper_links", []))
    for m in old[:-1]:
        db.delete(m)
    target = old[-1]
    target.content, target.citations, target.status = content, citations, "complete"
    chat.updated_at = datetime.datetime.now(datetime.timezone.utc)
    if stale - keep:
        rows = db.scalars(select(LibraryPaper).where(
            LibraryPaper.user_id == user.id, LibraryPaper.chat_id == chat.id,
            LibraryPaper.link.in_(stale - keep)))
        for r in rows:
            if not (r.paper_metadata or {}).get("is_uploaded"):
                db.delete(r)
    db.commit()


def _history_from_db(db, chat, limit=4):
    rows = db.scalars(
        select(Message).where(Message.chat_id == chat.id, Message.status == "complete")
        .order_by(Message.created_at.desc()).limit(limit)).all()
    return [
        {"role": m.role, "content": (m.content or "")[: 1200 if m.role == "assistant" else 600]}
        for m in reversed(rows)
    ]

def _build_initial_state(
    req: ChatRequest,
    session_id: str,
    turn_id: str,
    history: list[dict] | None = None,
    previous_papers: list[dict] | None = None,
) -> dict:
    return {
        "query": req.query,
        "session_id": session_id,
        "turn_id": turn_id,
        "evidence_mode": req.evidence_mode,
        "response_mode": req.response_mode,
        "conversation_history": history if history is not None else [],
        "original_query": None,
        "is_followup": False,
        "output_instruction": None,
        "previous_papers": previous_papers or [],
        "refined_query": None,
        "search_terms": [],
        "search_queries": [],
        "query_understanding": None,
        "query_plan": None,
        "method_note": None,
        "answer_spec": None,
        "source_plan": None,
        "retrieval_plan": None,
        "evidence_contract": None,
        "evidence_matrix": {},
        "citation_audit": [],
        "math_verification": None,
        "primary_source_present": False,
        "verification_status": "not_run",

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
        "references": [],
        "needs_retry": False,
        "error": None,
        "validation_results": [],

        "graph_contradictions": [],
        "graph_entities": [],

        "low_confidence_results": False,

        "chart_spec_raw": None,
        "chart_url": None,
        "comparison_table_markdown": None,
        "comparison_table_caption": None,

        "needs_revision": False,
        "revision_count": 0,
        "revision_instruction": None,
        "revision_section_ids": [],

        "report_plan": None,
        "information_needs": [],
        "complexity_score": 0,
        "report_depth": "low",
        "target_word_count": 0,
        "module_plan": [],
        "module_evidence_map": {},
        "section_outputs": [],
        "dynamic_confidence": None,
        "cited_paper_ids": [],
        "report_notice": None,

        "query_embedding": None,
        "target_paper_k": 0,

        "preview_answer": "",
        "preview_streamed": False,
        "search_cache_hit": False,

        "reasoning_ledger": None,
        "epistemic_report": None,

        "eligible_papers": [],
        "background_papers": [],
        "ineligible_papers": [],
        "evidence_sufficiency": None,
        "research_subquestions": [],
        "evidence_coverage_matrix": [],

        "_request_id": "",
        "_streaming_enabled": False,
        "_cancel_check": None,
    }


def _build_paper_results(ranked_papers: list[dict]) -> list[PaperResult]:
    return [
        PaperResult(
            title=p.get("title", "Untitled"),
            authors=p.get("authors", []),
            summary=p.get("summary", ""),
            link=p.get("link", ""),
            published=p.get("published"),
            relevance_score=p.get("final_score"),
            source=p.get("source", "unknown"),
            is_uploaded=(p.get("source") == "user_upload"),
            file_url=p.get("file_url"),
        )
        for p in ranked_papers
    ]


def _safe_reference_entries(raw_refs: list) -> list[ReferenceEntry]:
    references: list[ReferenceEntry] = []

    for r in raw_refs or []:
        try:
            if isinstance(r, dict):
                data = r
            elif hasattr(r, "model_dump"):
                data = r.model_dump()
            else:
                continue

            references.append(ReferenceEntry(**data))
        except Exception:
            try:
                references.append(
                    ReferenceEntry(
                        id=int(r.get("id", 0) if isinstance(r, dict) else 0),
                        title=str(r.get("title", "") if isinstance(r, dict) else ""),
                        link=str(r.get("link", "") if isinstance(r, dict) else ""),
                        authors=list(r.get("authors", []) if isinstance(r, dict) else []),
                    )
                )
            except Exception:
                continue

    return references


def _build_stream_response(
    req: ChatRequest,
    session_id: str,
    turn_id: str,
    final_state: dict,
) -> ChatResponse:
    ranked_papers = final_state.get("ranked_papers", []) or []
    papers = _build_paper_results(ranked_papers)

    raw_refs = final_state.get("references", []) or []
    id_map = paper_id_to_ref_id_map(ranked_papers, raw_refs)
    references = _safe_reference_entries(raw_refs)

    final_answer = final_state.get("final_answer", "") or final_state.get(
        "preview_answer", ""
    )

    if not (final_answer or "").strip():
        parts = []

        for s in final_state.get("section_outputs", []) or []:
            content = (s.get("content") or "").strip()
            if not content:
                continue

            if s.get("abstained") or content.strip() == ABSTAIN_TEXT:
                continue

            title = s.get("title") or ""
            if title:
                parts.append(f"## {title}\n\n{content}\n")
            else:
                parts.append(content)

        final_answer = "\n".join(parts).strip()

    if not (final_answer or "").strip():
        final_answer = _EMPTY_ANSWER_FALLBACK

    answer = sanitize_for_web_preserving_math(
        rewrite_inline_citations(final_answer, id_map)
    )

    sections = []
    for s in final_state.get("section_outputs", []) or []:
        section = dict(s)
        section["content"] = rewrite_inline_citations(
            section.get("content", ""),
            id_map,
        )
        sections.append(section)

    return ChatResponse(
        answer=answer,
        session_id=session_id,
        turn_id=turn_id,
        papers=papers,
        citations=final_state.get("citations", []) or [],
        method_note=final_state.get("method_note"),
        disclaimer=get_disclaimer(),
        papers_below_threshold=final_state.get("papers_below_threshold", 0),
        graph_contradictions=final_state.get("graph_contradictions", []),
        graph_entities=final_state.get("graph_entities", []),
        response_mode=req.response_mode,
        references=references,
        chart_url=final_state.get("chart_url"),
        citation_audit=final_state.get("citation_audit", []),
        math_verification=final_state.get("math_verification"),
        primary_source_present=final_state.get("primary_source_present"),
        report_plan=final_state.get("report_plan"),
        sections=sections,
        information_needs=final_state.get("information_needs", []),
        complexity_score=final_state.get("complexity_score", 0),
        report_notice=final_state.get("report_notice"),
    )


def _finalize_chat_response_blocking(
    req: ChatRequest,
    session_id: str,
    turn_id: str,
    final_state: dict,
) -> ChatResponse:
    ranked_papers = final_state.get("ranked_papers", []) or []

    for p in ranked_papers:
        try:
            vector_store.upsert_paper(p, session_id)
        except Exception as e:
            print(
                f"[chat] vector_store persistence failed for "
                f"'{p.get('title', '?')}': {type(e).__name__}: {e}"
            )

    filename = generate_filename(
        turn_id,
        final_state.get("final_answer", ""),
    )

    response = _build_stream_response(req, session_id, turn_id, final_state)
    response.filename = filename
    return response


def _background_persist_and_filename(
    req: ChatRequest,
    session_id: str,
    turn_id: str,
    final_state: dict,
) -> str:
    ranked_papers = final_state.get("ranked_papers", []) or []

    for p in ranked_papers:
        try:
            vector_store.upsert_paper(p, session_id)
        except Exception as e:
            print(
                f"[chat] background vector_store persistence failed for "
                f"'{p.get('title', '?')}': {type(e).__name__}: {e}"
            )

    try:
        filename = generate_filename(
            turn_id,
            final_state.get("final_answer", ""),
        )
    except Exception as e:
        print(f"[chat] background filename generation failed: {type(e).__name__}: {e}")
        filename = ""

    return filename


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    session_id = req.session_id or str(uuid.uuid4())
    turn_id = req.turn_id or str(uuid.uuid4())
    chat_record = _get_or_create_chat(db, user, session_id, req.query, req.chat_id)
    schedule_title_generation(chat_record.id, req.query)
    history = _history_from_db(db, chat_record)
    previous = previous_papers_from_db(db, user.id, chat_record)
    print(f"[chat] chat_id={chat_record.id} history={len(history)} previous_papers={len(previous)}")
    _persist_message(db, chat_record, "user", req.query, status="complete")
    assistant_message = _create_message(db, chat_record, "assistant")

    initial_state = _build_initial_state(req, session_id, turn_id, history, previous)

    t0 = time.time()

    final_state = await research_graph.ainvoke(initial_state)
    final_state = await asyncio.to_thread(run_enrichment, final_state)
    original_ranked = final_state.get("ranked_papers") or []

    cited_ids_raw = final_state.get("cited_paper_ids") or []
    cited_ids = {str(x) for x in cited_ids_raw if x is not None}

    papers_for_save = original_ranked

    if cited_ids and original_ranked:
        filtered_for_save = [
            p
            for i, p in enumerate(original_ranked)
            if str(i) in cited_ids
        ]

        if filtered_for_save:
            papers_for_save = filtered_for_save
    elapsed = round(time.time() - t0, 1)
    print(f"[timing] {elapsed}s | mode={req.response_mode} | query='{req.query}'")

    response = await asyncio.to_thread(
        _finalize_chat_response_blocking,
        req,
        session_id,
        turn_id,
        final_state,
    )
    ranked = final_state.get("ranked_papers") or []
    meta = {"references": [r.model_dump() for r in response.references],
            **_answer_meta(req.response_mode, req.evidence_mode, req.query, ranked)}
    _replace_assistant_message(db, user, chat_record, req.query, response.answer, meta)
    save_papers(db, user.id, req.session_id, papers_for_save, chat_id=chat_record.id)
    return response


@router.post("/chat/stream")
@limiter.limit("30/minute")
async def chat_stream(
    request: Request,
    req: ChatRequest,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    if not req.request_id:
        raise HTTPException(
            status_code=400,
            detail="request_id is required for /chat/stream.",
        )

    request_id = req.request_id
    session_id = req.session_id or str(uuid.uuid4())
    turn_id = req.turn_id or str(uuid.uuid4())
    chat_record = _get_or_create_chat(db, user, session_id, req.query, req.chat_id)
    schedule_title_generation(chat_record.id, req.query)
    history = _history_from_db(db, chat_record)
    previous = previous_papers_from_db(db, user.id, chat_record)
    print(f"[chat] chat_id={chat_record.id} history={len(history)} previous_papers={len(previous)}")
    _persist_message(db, chat_record, "user", req.query, status="complete")
    assistant_message = _create_message(db, chat_record, "assistant")
    chat_id = str(chat_record.id)
    message_id = assistant_message.id
    user_id = user.id
    async def event_stream():
        db_gen = get_db()
        db = next(db_gen)
        assistant_message = db.get(Message, message_id)
        cancellation.register(request_id)
        assistant_content = ""
        status_steps: list[dict] = []
        finished = False
        try:

            if req.response_mode in ("researched", "graph_research"):
                yield sse_event(
                    "notice",
                    message=(
                        "Deep research mode can take around 25–35 seconds. "
                        "Progress will appear as it runs."
                    ),
                )

            state: AgentState = _build_initial_state(req, session_id, turn_id, history, previous)

            loop = asyncio.get_running_loop()
            bridge_register(request_id, loop)

            state["_request_id"] = request_id
            state["_streaming_enabled"] = True
            state["_cancel_check"] = lambda: cancellation.is_cancelled(request_id)

            t0 = time.time()
            graph_error: list = []

            async def _run_graph():
                try:
                    async for update in research_graph.astream(
                        state,
                        stream_mode="updates",
                    ):
                        if cancellation.is_cancelled(request_id):
                            return

                        for node_name, delta in update.items():
                            state.update(delta)
                            bridge_push(request_id, ("progress", node_name, delta))

                    bridge_push(request_id, ("graph_done", None))
                except Exception as e:
                    print(f"[chat_stream] graph execution failed: {type(e).__name__}: {e}")
                    graph_error.append(e)
                    bridge_push(request_id, ("graph_done", None))

            graph_task = asyncio.create_task(_run_graph())

            sections_streamed = False

            while True:
                if cancellation.is_cancelled(request_id):
                    yield sse_event("cancelled")
                    return

                event = await bridge_get(request_id, timeout=0.15)

                if event is None:
                    if graph_task.done():
                        break
                    continue

                etype = event[0]

                if etype == "progress":
                    node_name, delta = event[1], event[2]

                    detail = None
                    items = None

                    if node_name == "report_plan":
                        notice = delta.get("report_notice") or state.get("report_notice")
                        if notice:
                            yield sse_event("notice", message=notice)

                    elif node_name in ("plan_query", "build_retrieval_plan", "search"):
                        if req.evidence_mode != "uploaded":
                            rp = delta.get("retrieval_plan") or state.get("retrieval_plan") or {}
                            qs = [i.get("query") for i in rp.get("intents", []) if i.get("query")]
                            detail = qs[0] if qs else req.query
                            items = qs[:4] or None
                        else:
                            queries = delta.get("search_queries") or state.get("search_queries")
                            if queries:
                                detail = (
                                    queries[0]
                                    if isinstance(queries, list) and queries
                                    else str(queries)
                                )

                    elif node_name in ("rank", "validate"):
                        papers = delta.get("ranked_papers") or state.get("ranked_papers")
                        if papers:
                            items = [
                                p.get("title", "")
                                for p in papers[:5]
                                if p.get("title")
                            ]

                    step_str = progress_event(node_name, detail=detail, items=items, evidence_mode=req.evidence_mode)
                    try:
                        status_steps.append(json.loads(step_str[len("data:"):].strip()))
                    except Exception:
                        pass
                    yield step_str

                elif etype == "llm_token":
                    sections_streamed = True
                    assistant_content += event[1]
                    _update_message(db, assistant_message, assistant_content)
                    yield sse_event("token", text=event[1], kind="final")

                elif etype == "section":
                    _mid, content = event[1], event[2]
                    sections_streamed = True
                    assistant_content += content
                    _update_message(db, assistant_message, assistant_content)
                    async for evt in stream_section_words(
                        content,
                        cancel_check=lambda: cancellation.is_cancelled(request_id),
                        kind="final",
                    ):
                        yield evt
                        await asyncio.sleep(0.01) 

                elif etype == "graph_done":
                    break

            await graph_task
            original_ranked = state.get("ranked_papers") or []

            cited_ids_raw = state.get("cited_paper_ids") or []
            cited_ids = {str(x) for x in cited_ids_raw if x is not None}

            papers_for_save = original_ranked

            if cited_ids and original_ranked:
                filtered_for_save = [
                    p
                    for i, p in enumerate(original_ranked)
                    if str(i) in cited_ids
                ]

                if filtered_for_save:
                    papers_for_save = filtered_for_save
            if graph_error:
                _update_message(db, assistant_message, assistant_content, status="failed")
                yield sse_event(
                    "error",
                    message="Something went wrong while generating this answer.",
                )
                return

            elapsed = round(time.time() - t0, 1)
            print(
                f"[timing] {elapsed}s | mode={req.response_mode} | "
                f"query='{req.query}' | streamed"
            )

            if not sections_streamed:
                refs = state.get("references") or []
                id_map = paper_id_to_ref_id_map(
                    state.get("ranked_papers") or [],
                    refs,
                )

                final_answer = state.get("final_answer", "") or state.get(
                    "preview_answer", ""
                )

                if final_answer:
                    final_answer = sanitize_for_web_preserving_math(
                        rewrite_inline_citations(final_answer, id_map)
                    )

                final_status = {}

                async for evt in stream_text_chunks_async(
                    final_answer,
                    cancel_check=lambda: cancellation.is_cancelled(request_id),
                    kind="final",
                    status=final_status,
                ):
                    yield evt

                if final_status.get("completed") is False:
                    _update_message(db, assistant_message, final_answer, status="stopped")
                    yield sse_event("cancelled")
                    return
                assistant_content = final_answer
            try:
                save_papers(db, user_id, session_id, papers_for_save, chat_id=chat_id)
            except Exception as e:
                print(f"[chat_stream] save_papers failed: {type(e).__name__}: {e}")

            response = _build_stream_response(req, session_id, turn_id, state)
            response.chat_id = chat_id

            if sections_streamed and not (response.answer or "").strip() and assistant_content.strip():
                response.answer = assistant_content

            yield sse_event("result", payload=response.model_dump())

            assistant_content = response.answer or assistant_content
            meta = _answer_meta(req.response_mode, req.evidence_mode, req.query, state.get("ranked_papers") or [])
            citations_payload = {
                "references": [r.model_dump() for r in response.references],
                "status_steps": status_steps,
                **meta
            }
            _update_message(
                db,
                assistant_message,
                assistant_content,
                status="complete",
                citations=citations_payload
            )
            finished = True

            if not cancellation.is_cancelled(request_id):
                enriched_state = await asyncio.to_thread(run_enrichment, dict(state))
                state.update(enriched_state)

                if state.get("chart_url"):
                    yield sse_event(
                        "artifact",
                        artifact_type="chart",
                        url=state.get("chart_url"),
                        raw_spec=state.get("chart_spec_raw"),
                    )

                if state.get("comparison_table_markdown"):
                    yield sse_event(
                        "artifact",
                        artifact_type="comparison_table",
                        markdown=state.get("comparison_table_markdown"),
                        caption=state.get("comparison_table_caption"),
                    )

                if state.get("graph_entities"):
                    yield sse_event(
                        "artifact",
                        artifact_type="graph_entities",
                        entities=state.get("graph_entities"),
                    )

            if not cancellation.is_cancelled(request_id):
                filename = await asyncio.to_thread(
                    _background_persist_and_filename,
                    req,
                    session_id,
                    turn_id,
                    state,
                )

                if filename:
                    yield sse_event("filename", filename=filename)

            yield sse_event("done")

        finally:
            if not finished and assistant_message.status == "streaming":
                _update_message(db, assistant_message, assistant_content, status="stopped")
            bridge_cleanup(request_id)
            cancellation.cleanup(request_id)
            db_gen.close()

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
@router.post("/chat/retry", response_model=ChatResponse, include_in_schema=False)
async def regenerate(req: RegenerateRequest, user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    turn_id = req.turn_id or str(uuid.uuid4())

    if req.is_followup:
        followup_req = FollowupRequest(
            session_id=req.session_id,
            turn_id=turn_id,
            question=req.query,
            response_mode=req.response_mode,
        )

        from app.api.routes.followup import followup as run_followup

        result: FollowupResponse = await asyncio.to_thread(
            run_followup,
            followup_req,
            user,
            db,
        )

        return ChatResponse(
            answer=result.answer,
            session_id=req.session_id,
            turn_id=turn_id,
            papers=[],
            citations=result.sources,
            disclaimer=get_disclaimer(),
            response_mode=req.response_mode,
            references=result.references,
            chart_url=result.chart_url,
        )

    chat_req = ChatRequest(
        query=req.query,
        session_id=req.session_id,
        turn_id=turn_id,
        evidence_mode=req.evidence_mode,
        response_mode=req.response_mode,
    )
    chat_record = _get_or_create_chat(
        db, user, req.session_id, req.query, req.chat_id
    )

    history = _history_from_db(db, chat_record)
    if req.chat_id:
        cut = max(
            (i for i, m in enumerate(history)
             if m["role"] == "user" and m["content"].strip() == req.query.strip()[:600]),
            default=None,
        )
        if cut is not None:
            history = history[:cut]

    if not req.chat_id:
        schedule_title_generation(chat_record.id, req.query)
        _persist_message(db, chat_record, "user", req.query, status="complete")

    previous = previous_papers_from_db(db, user.id, chat_record)
    initial_state = _build_initial_state(
        chat_req, req.session_id, turn_id, history=history, previous_papers=previous
    )

    final_state = await research_graph.ainvoke(initial_state)
    final_state = await asyncio.to_thread(run_enrichment, final_state)

    response = await asyncio.to_thread(
        _finalize_chat_response_blocking,
        chat_req,
        req.session_id,
        turn_id,
        final_state,
    )
    response.chat_id = str(chat_record.id)
    ranked = final_state.get("ranked_papers") or []
    meta = {"references": [r.model_dump() for r in response.references],
            **_answer_meta(req.response_mode, req.evidence_mode, req.query, ranked)}
    _replace_assistant_message(db, user, chat_record, req.query, response.answer, meta)
    save_papers(db, user.id, req.session_id, ranked, chat_id=chat_record.id)
    return response