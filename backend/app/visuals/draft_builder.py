"""
Draft builder for Studio.

This module proposes an initial VisualSpec from a prompt.

For diagrams, it returns an AI-proposed structure.
For charts, prompt/conversation grounded builders live in spec_builder.py.

IMPORTANT:
This first version uses deterministic starter structures.
Replace the *_draft() functions with a constrained LLM structured-output
call later. The surrounding contract should stay the same:

    prompt -> valid VisualSpec -> render -> user confirms/refines
"""

from __future__ import annotations

import uuid
from typing import Literal, Optional

from app.visuals.schema import (
    VisualSpec,
    DiagramPayload,
    DiagramNode,
    DiagramEdge,
    Provenance,
    ProvenanceKind,
    GroundingSummary,
    recompute_grounding,
)


DiagramFamily = Literal["flowchart", "architecture", "dfd"]


def _ai(note: str = "AI-proposed structure") -> Provenance:
    return Provenance(
        kind=ProvenanceKind.AI_PROPOSED,
        note=note,
    )


def build_diagram_draft(
    session_id: str,
    family: DiagramFamily,
    prompt: str,
    source: str = "prompt",
    dfd_level: Optional[Literal[0, 1]] = None,
    conversation_context: Optional[str] = None,
) -> VisualSpec:
    """
    Build a draft DiagramPayload from a prompt.

    This endpoint is generation-first:
    - never return an empty diagram
    - mark structure as AI_PROPOSED
    - let the user refine/commit afterward
    """
    title = (prompt or "").strip().split("\n")[0][:80]

    if family == "flowchart":
        title = title or "Process Flowchart"
        nodes, edges = _flowchart_draft(prompt, conversation_context)
        layout = "top_down"

    elif family == "architecture":
        title = title or "System Architecture"
        nodes, edges = _architecture_draft(prompt, conversation_context)
        layout = "layered"

    elif family == "dfd":
        level = dfd_level if dfd_level in (0, 1) else 0
        title = title or f"DFD Level {level}"
        nodes, edges = _dfd_draft(prompt, conversation_context, level)
        layout = "top_down"

    else:
        raise ValueError(f"Unsupported diagram family: {family}")

    payload = DiagramPayload(
        kind=family,
        layout=layout,
        nodes=nodes,
        edges=edges,
        dfd_level=dfd_level if family == "dfd" else None,
    )

    spec = VisualSpec(
        visual_id=str(uuid.uuid4()),
        session_id=session_id,
        title=title,
        caption="AI draft — review and refine before use.",
        grounding=GroundingSummary(
            level="draft",
            ai_proposed_count=len(nodes),
        ),
        payload=payload,
    )

    spec.grounding = recompute_grounding(payload)
    return spec


def _flowchart_draft(
    prompt: str,
    conversation_context: Optional[str],
) -> tuple[list[DiagramNode], list[DiagramEdge]]:
    """
    TODO: replace with constrained LLM output.

    For now, return a sensible generic flowchart.
    """
    nodes = [
        DiagramNode(
            id="start",
            label="Start",
            node_type="terminal",
            provenance=_ai(),
        ),
        DiagramNode(
            id="input",
            label="Capture input",
            node_type="data",
            provenance=_ai(),
        ),
        DiagramNode(
            id="process",
            label="Process request",
            node_type="process",
            provenance=_ai(),
        ),
        DiagramNode(
            id="decision",
            label="Valid?",
            node_type="decision",
            provenance=_ai(),
        ),
        DiagramNode(
            id="output",
            label="Produce output",
            node_type="data",
            provenance=_ai(),
        ),
        DiagramNode(
            id="end",
            label="End",
            node_type="terminal",
            provenance=_ai(),
        ),
    ]

    edges = [
        DiagramEdge(source="start", target="input"),
        DiagramEdge(source="input", target="process"),
        DiagramEdge(source="process", target="decision"),
        DiagramEdge(source="decision", target="output", label="yes"),
        DiagramEdge(source="decision", target="process", label="no"),
        DiagramEdge(source="output", target="end"),
    ]

    return nodes, edges


def _architecture_draft(
    prompt: str,
    conversation_context: Optional[str],
) -> tuple[list[DiagramNode], list[DiagramEdge]]:
    """
    TODO: replace with constrained LLM output.

    For now, return a clean layered architecture starter.
    """
    nodes = [
        DiagramNode(
            id="client",
            label="Client / UI",
            node_type="external",
            layer=0,
            provenance=_ai(),
        ),
        DiagramNode(
            id="gateway",
            label="API Gateway",
            node_type="process",
            layer=1,
            provenance=_ai(),
        ),
        DiagramNode(
            id="auth",
            label="Auth Service",
            node_type="process",
            layer=2,
            provenance=_ai(),
        ),
        DiagramNode(
            id="core",
            label="Core Service",
            node_type="process",
            layer=2,
            provenance=_ai(),
        ),
        DiagramNode(
            id="db",
            label="Database",
            node_type="store",
            layer=3,
            provenance=_ai(),
        ),
    ]

    edges = [
        DiagramEdge(source="client", target="gateway", label="requests"),
        DiagramEdge(source="gateway", target="auth", label="authn"),
        DiagramEdge(source="gateway", target="core", label="route"),
        DiagramEdge(source="core", target="db", label="read/write"),
    ]

    return nodes, edges


def _dfd_draft(
    prompt: str,
    conversation_context: Optional[str],
    level: Literal[0, 1],
) -> tuple[list[DiagramNode], list[DiagramEdge]]:
    """
    TODO: replace with constrained LLM output.

    For now, return valid DFD level 0/1 starters.
    """
    if level == 0:
        nodes = [
            DiagramNode(
                id="user",
                label="User",
                node_type="external",
                provenance=_ai(),
            ),
            DiagramNode(
                id="system",
                label="0. System",
                node_type="process",
                provenance=_ai(),
            ),
            DiagramNode(
                id="store",
                label="Records",
                node_type="store",
                provenance=_ai(),
            ),
        ]

        edges = [
            DiagramEdge(source="user", target="system", label="input"),
            DiagramEdge(source="system", target="user", label="output"),
            DiagramEdge(source="system", target="store", label="persist"),
        ]

        return nodes, edges

    nodes = [
        DiagramNode(
            id="user",
            label="User",
            node_type="external",
            provenance=_ai(),
        ),
        DiagramNode(
            id="intake",
            label="1. Intake",
            node_type="process",
            provenance=_ai(),
        ),
        DiagramNode(
            id="process",
            label="2. Process",
            node_type="process",
            provenance=_ai(),
        ),
        DiagramNode(
            id="store",
            label="Records",
            node_type="store",
            provenance=_ai(),
        ),
    ]

    edges = [
        DiagramEdge(source="user", target="intake", label="request"),
        DiagramEdge(source="intake", target="store", label="write"),
        DiagramEdge(source="store", target="process", label="read"),
        DiagramEdge(source="process", target="user", label="result"),
    ]

    return nodes, edges