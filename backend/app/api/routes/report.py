import asyncio
import datetime
import json
import time
import uuid
import io
import traceback
from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.agents.graph import research_graph
from app.agents.nodes.report_source_node import build_source_text, extract_records, ExtractionError
from app.agents.nodes.report_structure_node import (
    RequestAnalysis, StructureSection, ReportStructureDraft, build_structure_draft,
    structure_to_plan, structure_to_contracts, build_brief, detect_report_type,
)
from app.agents.nodes.retrieve_uploaded_node import load_uploaded_full_text
from app.agents.report_modules import get_disclaimer
from app.api.routes.chat import (
    _get_or_create_chat, _persist_message, _create_message, _update_message,
    _build_initial_state, _build_paper_results, _safe_reference_entries,
)
from app.auth import get_current_user
from app.config import settings
from app.db.database import get_db
from app.db.models import Chat, Message, ResearchSession, User
from app.models.schemas import ChatRequest, ConfirmedRecord, ReportPrepareRequest, ReferenceEntry
from app.services import cancellation
from app.services.citation_grounding import ground_text
from app.services.filename_service import generate_filename
from app.services.library_store import save_papers
from app.services.llm_client import get_llm
from app.services.previous_papers import previous_papers_from_db
from app.services.reference_builder import CitationNumberer, paper_id_to_ref_id_map
from app.services.sse import (
    sse_event, progress_event, bridge_register, bridge_push, bridge_get,
    bridge_cleanup, stream_section_words,
)
from app.utils.text_sanitizer import sanitize_for_web_preserving_math
from langchain_core.messages import SystemMessage, HumanMessage

router = APIRouter(tags=["report"])
limiter = Limiter(key_func=get_remote_address)
log_print = print


class ReportStructureRequest(BaseModel):
    query: str = Field(min_length=3, max_length=12000)
    session_id: Optional[str] = None
    evidence_mode: Literal["literature", "uploaded", "blended"] = "literature"
    guideline_text: Optional[str] = None


class StructureSectionInput(BaseModel):
    section_id: str
    title: str
    level: int = 1
    purpose: str = ""
    reason: str = ""
    structure_source: str = "llm_default"
    evidence_required: bool = False
    target_words: int = 250
    data_scope: str = "all"


class ReportRunRequest(BaseModel):
    query: str = Field(min_length=3, max_length=12000)
    session_id: str
    chat_id: Optional[str] = None
    request_id: str
    evidence_mode: Literal["literature", "uploaded", "blended"] = "literature"
    report_type: Optional[str] = None
    execution_path: Optional[str] = None
    title: Optional[str] = None
    guideline_text: Optional[str] = None
    analysis: Optional[dict] = None
    sections: list[StructureSectionInput] = Field(min_length=1, max_length=12)
    confirmed_source_records: Optional[list[ConfirmedRecord]] = None


class ReportRefineRequest(BaseModel):
    chat_id: str
    message_id: str
    instruction: str = Field(min_length=2, max_length=4000)
    request_id: str


class SectionPatch(BaseModel):
    section_id: str
    content: str | None = None
    title: str | None = Field(None, min_length=1, max_length=200)


class ReportPatchRequest(BaseModel):
    chat_id: str
    message_id: str
    sections: list[SectionPatch] = Field(default_factory=list)
    title: str | None = Field(None, min_length=1, max_length=200)


def _own_message(db: DBSession, user: User, chat_id: str, message_id: str) -> Message:
    try:
        cid, mid = uuid.UUID(chat_id), uuid.UUID(message_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid identifier.") from exc
    msg = db.get(Message, mid)
    if not msg or msg.chat_id != cid or msg.chat.user_id != user.id:
        raise HTTPException(status_code=404, detail="Report not found.")
    return msg


@router.post("/report/structure", response_model=ReportStructureDraft)
@limiter.limit("20/minute")
async def report_structure(request: Request, req: ReportStructureRequest,
                           user: User = Depends(get_current_user),
                           db: DBSession = Depends(get_db)):
    if req.session_id:
        try:
            sid = uuid.UUID(req.session_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid session identifier.") from exc
        owned = db.scalar(select(ResearchSession).where(
            ResearchSession.id == sid, ResearchSession.user_id == user.id))
        if not owned:
            raise HTTPException(status_code=404, detail="Session not found.")
    draft = await build_structure_draft(req.query, req.guideline_text or "")
    return draft


@router.post("/report/prepare")
@limiter.limit("10/minute")
async def report_prepare(request: Request, req: ReportPrepareRequest,
                         user: User = Depends(get_current_user),
                         db: DBSession = Depends(get_db)):
    texts: list[str] = []
    if req.evidence_mode in ("uploaded", "blended") and req.session_id:
        try:
            session_uuid = uuid.UUID(req.session_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid session identifier.") from exc
        owned = db.scalar(select(ResearchSession).where(
            ResearchSession.id == session_uuid, ResearchSession.user_id == user.id))
        if not owned:
            raise HTTPException(status_code=404, detail="Session not found.")
        texts = await asyncio.to_thread(
            load_uploaded_full_text, req.session_id, settings.REPORT_EXTRACT_MAX_CHARS)
    source_text, truncated = build_source_text(req.query, texts)
    extraction_failed = False
    try:
        records, dropped = await asyncio.to_thread(extract_records, source_text)
    except ExtractionError:
        records, dropped, extraction_failed = [], [], True
    suggested_type = await asyncio.to_thread(detect_report_type, req.query) or "general"
    word_count = len((req.query or "").split())
    if suggested_type == "general" and word_count <= 18 and len(records) <= 3 and not extraction_failed:
        path = "simple"
    elif suggested_type in ("financial_ledger", "scientific_research") or len(records) >= 8:
        path = "deep"
    else:
        path = "standard"
    return {
        "suggested_type": suggested_type,
        "suggested_execution_path": path,
        "working_title": (req.query or "").strip().replace("\n", " ")[:110] or "Report",
        "records": records,
        "dropped_count": len(dropped),
        "truncated": truncated,
        "extraction_failed": extraction_failed,
    }


@router.post("/report/run/stream")
@limiter.limit("10/minute")
async def report_run_stream(request: Request, req: ReportRunRequest,
                            user: User = Depends(get_current_user),
                            db: DBSession = Depends(get_db)):
    request_id = req.request_id
    turn_id = str(uuid.uuid4())
    chat_record = _get_or_create_chat(db, user, req.session_id, req.query, req.chat_id)
    chat_record.kind = "report"
    chat_id = str(chat_record.id)
    _persist_message(db, chat_record, "user", req.query, status="complete")
    assistant_message = _create_message(db, chat_record, "assistant")
    message_uuid = assistant_message.id
    message_id = str(message_uuid)
    user_id = user.id
    history: list[dict] = []
    previous = previous_papers_from_db(db, user.id, chat_record)

    sections_in = [StructureSection(**s.model_dump()) for s in req.sections]
    plan = structure_to_plan(sections_in)
    contracts = structure_to_contracts(sections_in)
    report_type = req.report_type or "general"
    title = req.title or " ".join(req.query.split())[:110]

    chat_req = ChatRequest(
        query=req.query, session_id=req.session_id, chat_id=chat_id, turn_id=turn_id,
        evidence_mode=req.evidence_mode, response_mode="researched",
        report_mode=True, report_type=report_type if report_type in (
            "scientific_research", "field_survey", "business_operational",
            "financial_ledger", "technical_project", "general") else "general",
        report_title=title,
        confirmed_source_records=req.confirmed_source_records,
    )
    state = _build_initial_state(chat_req, req.session_id, turn_id, history, previous)
    state.update({
        "report_section_plan": plan,
        "report_section_contracts": contracts,
        "report_structure_approved": True,
        "report_structure_draft": req.analysis,
        "report_guideline_text": req.guideline_text,
        "report_brief": build_brief(req.query, req.evidence_mode, report_type, title),
        "report_execution_path": req.execution_path or "standard",
        "report_title": title,
    })

    async def event_stream():
        db_gen = get_db()
        db2 = next(db_gen)
        msg = db2.get(Message, message_uuid)
        cancellation.register(request_id)
        status_steps: list[dict] = []
        finished = False
        try:
            loop = asyncio.get_running_loop()
            bridge_register(request_id, loop)
            state["_request_id"] = request_id
            state["_streaming_enabled"] = True
            state["_cancel_check"] = lambda: cancellation.is_cancelled(request_id)
            t0 = time.time()
            graph_error: list = []

            async def _run_graph():
                try:
                    async for update in research_graph.astream(state, stream_mode="updates"):
                        if cancellation.is_cancelled(request_id):
                            return
                        for node_name, delta in update.items():
                            if not isinstance(delta, dict):
                                continue
                            state.update(delta)
                            bridge_push(request_id, ("progress", node_name, delta))
                    bridge_push(request_id, ("graph_done", None))
                except Exception as e:
                    log_print(f"[report_run] graph failed:\n{traceback.format_exc()}")
                    graph_error.append(e)
                    bridge_push(request_id, ("graph_done", None))

            graph_task = asyncio.create_task(_run_graph())
            last_sent = time.time()
            while True:
                if cancellation.is_cancelled(request_id):
                    yield sse_event("cancelled")
                    return
                event = await bridge_get(request_id, timeout=0.15)
                if event is None:
                    if graph_task.done():
                        break
                    if time.time() - last_sent > 15:
                        last_sent = time.time()
                        yield sse_event("ping")
                    continue
                last_sent = time.time()
                etype = event[0]
                if etype == "progress":
                    node_name, delta = event[1], event[2]
                    detail = (delta or {}).get("detail") if node_name == "report_writer" else None
                    step = progress_event(node_name, detail=detail, evidence_mode=req.evidence_mode)
                    try:
                        status_steps.append(json.loads(step[len("data:"):].strip()))
                    except Exception:
                        pass
                    yield step
                elif etype == "report_section_draft":
                    _, mid, sec_title, content = event
                    yield sse_event("report_section", section_id=mid,
                                    title=sec_title, markdown=content or "", final=False)
                elif etype == "section":
                    mid, content = event[1], event[2]
                    yield sse_event("report_section", section_id=mid,
                                    markdown=content or "", final=True)
                elif etype == "graph_done":
                    break
            await graph_task
            if graph_error:
                _update_message(db2, msg, "", status="failed")
                yield sse_event("error", message="Something went wrong while generating this report.")
                return

            ranked = state.get("ranked_papers") or []
            references = _safe_reference_entries(state.get("references") or [])
            id_map = paper_id_to_ref_id_map(ranked, [r.model_dump() for r in references])
            numberer = CitationNumberer(id_map)
            final_sections = []
            for s in state.get("section_outputs") or []:
                final_sections.append({
                    "section_id": s.get("module_id") or s.get("section_id"),
                    "title": s.get("title"),
                    "content": numberer.rewrite(s.get("content") or ""),
                    "confidence": s.get("confidence", "medium"),
                })
            answer = sanitize_for_web_preserving_math(state.get("final_answer") or "")
            cited_ids = {str(x) for x in (state.get("cited_paper_ids") or [])}
            papers_for_save = ranked
            if cited_ids and ranked:
                filtered = [p for i, p in enumerate(ranked) if str(i) in cited_ids]
                papers_for_save = filtered or ranked
            sources = []
            ref_to_paper = {int(rid): int(pid) for pid, rid in id_map.items()}
            for r in references:
                pid = ref_to_paper.get(int(r.id))
                excerpt = (ranked[pid].get("summary") or "")[:900] if pid is not None and pid < len(ranked) else ""
                sources.append({"id": r.id, "title": r.title, "excerpt": excerpt})
            artifact = {
                "title": state.get("report_title") or title,
                "query": req.query,
                "structure": [s.model_dump() for s in sections_in],
                "sections": final_sections,
                "references": [r.model_dump() for r in references],
                "sources": sources,
                "records": [r.model_dump() for r in (req.confirmed_source_records or [])],
                "evidence_mode": req.evidence_mode,
                "report_type": report_type,
                "paper_links": [p.get("link") for p in ranked if p.get("link")],
                "analysis": req.analysis,
            }
            payload = {
                "turn_id": turn_id, "chat_id": chat_id, "message_id": message_id,
                "title": artifact["title"], "answer": answer,
                "references": [r.model_dump() for r in references],
                "sections": final_sections,
                "papers": [p.model_dump() for p in _build_paper_results(ranked)],
                "method_note": state.get("method_note"),
                "disclaimer": get_disclaimer(),
            }
            yield sse_event("result", payload=payload)
            citations_payload = {
                "references": [r.model_dump() for r in references],
                "status_steps": status_steps,
                "report_mode": True,
                "report_artifact": artifact,
                "evidence_mode": req.evidence_mode,
                "source_query": req.query,
                "paper_links": artifact["paper_links"],
            }
            _update_message(db2, msg, answer, status="complete", citations=citations_payload)
            finished = True
            try:
                save_papers(db2, user_id, req.session_id, papers_for_save, chat_id=chat_id)
            except Exception as e:
                log_print(f"[report_run] save_papers failed: {type(e).__name__}: {e}")
            filename = await asyncio.to_thread(generate_filename, turn_id, answer)
            if filename:
                yield sse_event("filename", filename=filename)
            yield sse_event("done")
        finally:
            if not finished and msg.status == "streaming":
                _update_message(db2, msg, "", status="stopped")
            bridge_cleanup(request_id)
            cancellation.cleanup(request_id)
            db_gen.close()

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/report/latest/{session_id}")
async def report_latest(session_id: str, user: User = Depends(get_current_user),
                        db: DBSession = Depends(get_db)):
    try:
        sid = uuid.UUID(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid session identifier.") from exc
    owned = db.scalar(select(ResearchSession).where(
        ResearchSession.id == sid, ResearchSession.user_id == user.id))
    if not owned:
        raise HTTPException(status_code=404, detail="Session not found.")
    rows = db.scalars(
        select(Message)
        .join(Chat, Message.chat_id == Chat.id)
        .where(Chat.session_id == sid, Chat.user_id == user.id,
               Message.role == "assistant", Message.status == "complete")
        .order_by(Message.created_at.desc()).limit(15)
    ).all()
    for m in rows:
        art = (m.citations or {}).get("report_artifact")
        if art:
            return {"chat_id": str(m.chat_id), "message_id": str(m.id),
                    "artifact": art, "created_at": m.created_at.isoformat()}
    return None


@router.patch("/report/sections")
async def report_patch_sections(req: ReportPatchRequest,
                                user: User = Depends(get_current_user),
                                db: DBSession = Depends(get_db)):
    msg = _own_message(db, user, req.chat_id, req.message_id)
    cit = dict(msg.citations or {})
    art = dict(cit.get("report_artifact") or {})
    if not art:
        raise HTTPException(status_code=404, detail="Report not found.")
    patches = {p.section_id: p for p in req.sections}
    for sec in art.get("sections") or []:
        p = patches.get(sec.get("section_id"))
        if p:
            if p.content is not None:
                sec["content"] = p.content
            if p.title:
                sec["title"] = p.title.strip()
    if req.title:
        art["title"] = req.title.strip()
    answer = _rebuild_answer(art)
    art["sections"] = art.get("sections")
    cit["report_artifact"] = art
    _update_message(db, msg, answer, citations=cit)
    return {"ok": True, "answer": answer}


@router.post("/report/refine/stream")
@limiter.limit("20/minute")
async def report_refine_stream(request: Request, req: ReportRefineRequest,
                               user: User = Depends(get_current_user),
                               db: DBSession = Depends(get_db)):
    msg = _own_message(db, user, req.chat_id, req.message_id)
    message_id = req.message_id
    cit = dict(msg.citations or {})
    art = dict(cit.get("report_artifact") or {})
    if not art:
        raise HTTPException(status_code=404, detail="Report not found.")
    sections = [dict(s) for s in (art.get("sections") or [])]
    sources = art.get("sources") or []
    texts_by_id = {str(s["id"]): f"{s.get('title','')}. {s.get('excerpt','')}" for s in sources}
    extra = "\n".join([str(r.get("value_raw") or r.get("value") or "")
                       for r in (art.get("records") or [])] + [art.get("query") or ""])
    cancellation.register(req.request_id)

    async def event_stream():
        finished = False
        try:
            listing = "\n".join(f"- [{s['section_id']}] {s['title']}" for s in sections)
            target_prompt = (
                f"INSTRUCTION: {req.instruction}\nSECTIONS:\n{listing}\n"
                'Return JSON only: {"section_ids": ["..."], "global": false}. '
                "Pick the sections that must be rewritten to satisfy the instruction; "
                "set global=true only if the instruction restructures the whole report.")
            try:
                llm_fast = get_llm(temperature=0, task="fast")
                raw = await asyncio.to_thread(
                    llm_fast.invoke_json_mode,
                    [SystemMessage(content="You route edit instructions to report sections. Return only JSON."),
                     HumanMessage(content=target_prompt)],
                    config={"timeout": 8},
                )
                ids = [str(x) for x in (raw or {}).get("section_ids", [])] if isinstance(raw, dict) else []
                glob = bool((raw or {}).get("global")) if isinstance(raw, dict) else False
            except Exception:
                ids, glob = [], False
            valid = {s["section_id"] for s in sections}
            ids = [i for i in ids if i in valid]
            if glob or not ids:
                ids = [s["section_id"] for s in sections if s["section_id"] != "references"] or valid
            llm = get_llm(temperature=0, task="strong")
            allowed = ", ".join(texts_by_id.keys()) or "none"
            changed = []
            for sid in ids:
                if cancellation.is_cancelled(req.request_id):
                    yield sse_event("cancelled")
                    return
                sec = next(s for s in sections if s["section_id"] == sid)
                prompt = (
                    f"REPORT TITLE: {art.get('title','')}\nSECTION: {sec['title']}\n"
                    f"CURRENT CONTENT:\n{sec['content']}\n\n"
                    f"USER INSTRUCTION: {req.instruction}\n\n"
                    f"Rewrite ONLY this section to satisfy the instruction.\n"
                    f"Keep every user-provided number exactly as written. "
                    f"Keep citation markers [N] only with N in {{{allowed}}}; cite only what the source states. "
                    f"Markdown only, no heading, no <think>.")
                try:
                    raw = await asyncio.to_thread(
                        llm.invoke,
                        [SystemMessage(content="You rewrite one report section. Markdown only."),
                         HumanMessage(content=prompt)],
                        config={"timeout": settings.REPORT_SECTION_TIMEOUT_DEEP},
                    )
                    new = (raw.content or "").strip()
                except Exception as e:
                    log_print(f"[refine] section {sid} failed: {type(e).__name__}: {e}")
                    continue
                if len(new.split()) < 15:
                    continue
                if texts_by_id:
                    new, drops = ground_text(new, texts_by_id, None,
                                             numeric_check=getattr(settings, "GROUNDING_NUMERIC_CHECK_ENABLED", True),
                                             extra_text=extra)
                sec["content"] = new
                changed.append(sid)
                yield sse_event("report_section", section_id=sid,
                                title=sec["title"], markdown=new, final=True)
            if changed:
                answer = _rebuild_answer(art)
                cit2 = dict(msg.citations or {})
                cit2["report_artifact"] = art
                _update_message(db, msg, answer, citations=cit2)
                yield sse_event("result", payload={"answer": answer, "changed": changed})
            else:
                yield sse_event("error", message="No section could be rewritten for that instruction.")
            finished = True
            yield sse_event("done")
        finally:
            cancellation.cleanup(req.request_id)

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/report/guideline-text")
@limiter.limit("20/minute")
async def report_guideline_text(request: Request, file: UploadFile = File(...),
                                user: User = Depends(get_current_user)):
    data = await file.read()
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large.")

    def _extract() -> str:
        from pypdf import PdfReader
        return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages[:30])

    try:
        text = await asyncio.to_thread(_extract)
    except Exception:
        text = ""
    return {"text": text[:20000]}


def _rebuild_answer(art: dict) -> str:
    parts = [f"# {art.get('title') or 'Report'}\n"]
    for s in art.get("sections") or []:
        parts.append(f"## {s.get('title')}\n\n{s.get('content')}\n")
    return "\n".join(parts).strip()