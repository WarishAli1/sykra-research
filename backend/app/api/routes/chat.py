import asyncio
import time
import uuid

from fastapi import APIRouter, HTTPException
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


router = APIRouter()


def _build_initial_state(req: ChatRequest, session_id: str, turn_id: str) -> dict:
    return {
        "query": req.query,
        "session_id": session_id,
        "turn_id": turn_id,
        "evidence_mode": req.evidence_mode,
        "response_mode": req.response_mode,
        "conversation_history": req.conversation_history,

        "refined_query": None,
        "search_terms": [],
        "search_queries": [],
        "query_understanding": None,
        "query_plan": None,

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

    if final_answer:
        answer = sanitize_for_web_preserving_math(
            rewrite_inline_citations(final_answer, id_map)
        )
    else:
        answer = ""

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
async def chat(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())
    turn_id = req.turn_id or str(uuid.uuid4())

    initial_state = _build_initial_state(req, session_id, turn_id)

    t0 = time.time()

    final_state = await research_graph.ainvoke(initial_state)
    final_state = await asyncio.to_thread(run_enrichment, final_state)

    elapsed = round(time.time() - t0, 1)
    print(f"[timing] {elapsed}s | mode={req.response_mode} | query='{req.query}'")

    return await asyncio.to_thread(
        _finalize_chat_response_blocking,
        req,
        session_id,
        turn_id,
        final_state,
    )


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    if not req.request_id:
        raise HTTPException(
            status_code=400,
            detail="request_id is required for /chat/stream.",
        )

    request_id = req.request_id
    session_id = req.session_id or str(uuid.uuid4())
    turn_id = req.turn_id or str(uuid.uuid4())

    async def event_stream():
        cancellation.register(request_id)

        try:
            if req.response_mode == "graph_research":
                graph_store.clear_session(session_id)

            if req.response_mode in ("researched", "graph_research"):
                yield sse_event(
                    "notice",
                    message=(
                        "Deep research mode can take around 25–35 seconds. "
                        "Progress will appear as it runs."
                    ),
                )

            state: AgentState = _build_initial_state(req, session_id, turn_id)

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

                    elif node_name in ("plan_query", "search"):
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

                    yield progress_event(node_name, detail=detail, items=items)

                elif etype == "llm_token":
                    sections_streamed = True
                    yield sse_event("token", text=event[1], kind="final")

                elif etype == "section":
                    _mid, content = event[1], event[2]
                    sections_streamed = True

                    async for evt in stream_section_words(
                        content,
                        cancel_check=lambda: cancellation.is_cancelled(request_id),
                        kind="final",
                    ):
                        yield evt

                elif etype == "graph_done":
                    break

            await graph_task

            if graph_error:
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
                    yield sse_event("cancelled")
                    return

            response = _build_stream_response(req, session_id, turn_id, state)
            yield sse_event("result", payload=response.model_dump())

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
            bridge_cleanup(request_id)
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
async def regenerate(req: RegenerateRequest):
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

    initial_state = _build_initial_state(chat_req, req.session_id, turn_id)

    final_state = await research_graph.ainvoke(initial_state)
    final_state = await asyncio.to_thread(run_enrichment, final_state)

    return await asyncio.to_thread(
        _finalize_chat_response_blocking,
        chat_req,
        req.session_id,
        turn_id,
        final_state,
    )