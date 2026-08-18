from typing import Literal, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.visuals.schema import VisualSpec, recompute_grounding
from app.visuals.renderers.chart_renderer import render_chart
from app.visuals.renderers.diagram_renderer import render as render_diagram
from app.services.vector_store import vector_store
from app.services.reference_builder import build_references

router = APIRouter()

_REGISTRY: dict[str, list[VisualSpec]] = {}


class GenerateRequest(BaseModel):
    spec: VisualSpec


class GroundedChartRequest(BaseModel):
    session_id: str
    path: Literal["papers", "web_search"]
    query: str = ""
    title: str = ""
    chart_type: Literal["bar", "line", "pie", "scatter"] = "bar"


class DraftRequest(BaseModel):
    session_id: str
    family: Literal["chart", "flowchart", "architecture", "dfd"]
    prompt: str
    source: Literal[
        "prompt",
        "manual",
        "papers",
        "conversation",
        "web_search",
    ] = "prompt"
    chart_type: Literal["bar", "line", "pie", "scatter"] = "bar"
    dfd_level: Optional[Literal[0, 1]] = None
    conversation_context: Optional[str] = None
    selected_paper_links: Optional[list[str]] = None


def _render_spec(spec: VisualSpec) -> str:
    if spec.payload.kind == "chart":
        return render_chart(spec)
    return render_diagram(spec)


@router.post("/generate")
def generate(req: GenerateRequest):
    spec = req.spec
    spec.grounding = recompute_grounding(spec.payload)
    spec.asset_path = _render_spec(spec)
    _REGISTRY.setdefault(spec.visual_id, []).append(spec)
    return {"visual_id": spec.visual_id, "revision": spec.revision,
            "asset_path": spec.asset_path, "grounding": spec.grounding}


@router.post("/generate/grounded")
def generate_grounded(req: GroundedChartRequest):
    """Paths 2 & 3: build a GROUNDED chart server-side via spec_builder."""
    from app.visuals.spec_builder import build_spec_from_papers, build_spec_from_web_search

    title = req.title or req.query or "Grounded chart"
    if req.path == "papers":
        ranked = [p for p in vector_store.get_session_papers(req.session_id) if p.get("title")][:10]
        if not ranked:
            raise HTTPException(400, "No papers in this session yet. Upload or research first.")
        references = build_references(ranked)
        spec = build_spec_from_papers(
            req.session_id, title, req.chart_type,
            list(range(len(ranked))), req.query, ranked, references,
        )
    else:
        spec = build_spec_from_web_search(
            req.session_id, title, req.chart_type, req.query, req.query,
        )
    spec.grounding = recompute_grounding(spec.payload)
    spec.asset_path = _render_spec(spec)
    _REGISTRY.setdefault(spec.visual_id, []).append(spec)
    return {"spec": spec, "asset_path": spec.asset_path, "grounding": spec.grounding}


@router.post("/draft")
def draft(req: DraftRequest):
    """
    Generation-first draft endpoint.

    This does NOT store the draft in _REGISTRY.
    It returns a rendered preview spec that the user can later commit
    via /generate or edit locally before committing.
    """
    from app.visuals.spec_builder import (
        build_spec_from_papers,
        build_spec_from_web_search,
        build_spec_from_prompt,
        build_spec_from_conversation,
    )
    from app.visuals.draft_builder import build_diagram_draft

    title = (req.prompt or "").strip().split("\n")[0][:80] or "Draft visual"
    warnings: list[str] = []
    missing_data: list[str] = []

    if req.family == "chart":
        if req.source == "papers":
            ranked = [
                p
                for p in vector_store.get_session_papers(req.session_id)
                if p.get("title")
            ][:10]

            if not ranked:
                raise HTTPException(
                    400,
                    "No papers in this session yet. Upload or research first.",
                )

            references = build_references(ranked)

            spec = build_spec_from_papers(
                req.session_id,
                title,
                req.chart_type,
                list(range(len(ranked))),
                req.prompt,
                ranked,
                references,
            )

        elif req.source == "web_search":
            spec = build_spec_from_web_search(
                req.session_id,
                title,
                req.chart_type,
                req.prompt,
                req.prompt,
            )

        elif req.source == "conversation":
            if not req.conversation_context or not req.conversation_context.strip():
                raise HTTPException(
                    400,
                    "No conversation context provided.",
                )

            spec = build_spec_from_conversation(
                req.session_id,
                title,
                req.chart_type,
                req.prompt,
                req.conversation_context,
            )

        else:
            spec = build_spec_from_prompt(
                req.session_id,
                title,
                req.chart_type,
                req.prompt,
            )

        if spec.grounding.level == "illustrative":
            missing_data.append(
                "No grounded/user numeric values found. "
                "Provide values directly or choose papers/web/conversation."
            )

    else:
        extra_context = req.conversation_context or ""

        if req.source == "papers":
            ranked = [
                p
                for p in vector_store.get_session_papers(req.session_id)
                if p.get("title")
            ][:10]

            if not ranked:
                warnings.append(
                    "No papers in this session yet. Drafting from prompt only."
                )
            else:
                paper_context = "\n\n".join(
                    f"Paper: {p.get('title', '')}\nSummary: {p.get('summary', '')}"
                    for p in ranked
                )
                extra_context = (
                    f"{extra_context}\n\n{paper_context}".strip()
                )

        spec = build_diagram_draft(
            session_id=req.session_id,
            family=req.family,
            prompt=req.prompt,
            source=req.source,
            dfd_level=req.dfd_level,
            conversation_context=extra_context or None,
        )

    spec.grounding = recompute_grounding(spec.payload)
    spec.asset_path = _render_spec(spec)

    return {
        "spec": spec,
        "asset_path": spec.asset_path,
        "grounding": spec.grounding,
        "warnings": warnings,
        "missing_data": missing_data,
    }


@router.post("/{visual_id}/revise")
def revise(visual_id: str, spec: VisualSpec):
    prev = _REGISTRY.get(visual_id)
    if not prev:
        raise HTTPException(404, "visual not found")
    spec.revision = prev[-1].revision + 1
    spec.grounding = recompute_grounding(spec.payload)
    spec.asset_path = _render_spec(spec) 
    prev.append(spec)
    return {"visual_id": visual_id, "revision": spec.revision,
            "asset_path": spec.asset_path, "grounding": spec.grounding}


@router.get("/{visual_id}")
def get(visual_id: str):
    revs = _REGISTRY.get(visual_id)
    if not revs:
        raise HTTPException(404)
    return {"current": revs[-1], "history": revs}


@router.get("/session/{session_id}")
def list_session(session_id: str):
    return {"visuals": [revs[-1] for revs in _REGISTRY.values()
                        if revs and revs[-1].session_id == session_id]}