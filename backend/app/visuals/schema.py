from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Literal, Optional, Union
from pydantic import BaseModel, Field, model_validator


class ProvenanceKind(str, Enum):
    USER_PROVIDED = "user_provided"
    GROUNDED      = "grounded"
    DERIVED       = "derived"
    ILLUSTRATIVE  = "illustrative"
    USER_EDITED   = "user_edited"
    AI_PROPOSED   = "ai_proposed"  


class Provenance(BaseModel):
    """Where one number/element came from. This is the anti-hallucination contract."""
    kind: ProvenanceKind
    source_paper_id: Optional[int] = None    
    source_ref_id: Optional[int] = None     
    source_url: Optional[str] = None
    source_quote: Optional[str] = None        
    derivation: Optional[str] = None        
    note: Optional[str] = None


class GroundingSummary(BaseModel):
    level: Literal[
        "user_provided",
        "grounded",
        "mixed",
        "illustrative",
        "draft",
    ]
    grounded_count: int = 0
    user_provided_count: int = 0
    illustrative_count: int = 0
    ai_proposed_count: int = 0
    citations: list[int] = Field(default_factory=list)
    note: Optional[str] = None


class ChartSeries(BaseModel):
    label: str
    values: list[Optional[float]] = Field(default_factory=list) 
    x_values: list[Optional[float]] = Field(default_factory=list)
    unit: Optional[str] = None
    provenance: list[Provenance] = Field(default_factory=list)


class ChartPayload(BaseModel):
    kind: Literal["chart"] = "chart"
    chart_type: Literal["bar", "line", "pie", "scatter"]
    categories: list[str] = Field(default_factory=list)
    series: list[ChartSeries] = Field(default_factory=list)
    x_label: Optional[str] = None
    y_label: Optional[str] = None
    log_y: bool = False
    show_values: bool = True


class DiagramNode(BaseModel):
    id: str
    label: str
    node_type: Literal["process", "terminal", "data", "external",
                       "store", "decision"] = "process"
    layer: Optional[int] = None                
    provenance: Optional[Provenance] = None     


class DiagramEdge(BaseModel):
    source: str
    target: str
    label: Optional[str] = None


class DiagramPayload(BaseModel):
    kind: Literal["flowchart", "architecture", "dfd", "diagram"]
    layout: Literal["top_down", "left_right", "layered"] = "top_down"
    nodes: list[DiagramNode] = Field(default_factory=list)
    edges: list[DiagramEdge] = Field(default_factory=list)
    dfd_level: Optional[Literal[0, 1]] = None


VisualPayload = Annotated[
    Union[ChartPayload, DiagramPayload],
    Field(discriminator="kind"),
]


class VisualSpec(BaseModel):
    """The editable, versionable unit. One spec -> one rendered asset per revision."""
    spec_version: int = 1
    visual_id: str
    session_id: str
    turn_id: Optional[str] = None
    revision: int = 1

    title: str
    caption: Optional[str] = None
    grounding: GroundingSummary
    payload: VisualPayload

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    asset_path: Optional[str] = None 

    @property
    def visual_type(self) -> str:
        return self.payload.kind

    @model_validator(mode="after")
    def _provenance_alignment(self):
        if isinstance(self.payload, ChartPayload):
            for s in self.payload.series:
                if s.provenance and len(s.provenance) != len(s.values):
                    raise ValueError(
                        f"series '{s.label}': provenance len {len(s.provenance)} "
                        f"!= values len {len(s.values)}"
                    )
        self.grounding = recompute_grounding(self.payload) if not self.grounding.citations \
            else self.grounding
        return self


def recompute_grounding(payload: VisualPayload) -> GroundingSummary:
    """Derive the summary badge from real provenance — never hand-set it."""
    kinds: list[ProvenanceKind] = []
    citations: list[int] = []
    if isinstance(payload, ChartPayload):
        for s in payload.series:
            for p in s.provenance:
                kinds.append(p.kind)
                if p.source_ref_id is not None and p.source_ref_id not in citations:
                    citations.append(p.source_ref_id)
    else:
        for n in payload.nodes:
            if n.provenance:
                kinds.append(n.provenance.kind)

    g = sum(k == ProvenanceKind.GROUNDED for k in kinds)
    u = sum(k == ProvenanceKind.USER_PROVIDED for k in kinds)
    i = sum(k == ProvenanceKind.ILLUSTRATIVE for k in kinds)
    a = sum(k == ProvenanceKind.AI_PROPOSED for k in kinds)

    if not kinds:
        if isinstance(payload, DiagramPayload) and payload.nodes:
            return GroundingSummary(
                level="user_provided",
                user_provided_count=len(payload.nodes),
            )
        return GroundingSummary(level="draft")

    if a and a == len(kinds):
        level = "draft"
    elif i and i == len(kinds):
        level = "illustrative"
    elif g and not u and not a:
        level = "grounded"
    elif u and not g and not a:
        level = "user_provided"
    else:
        level = "mixed"

    return GroundingSummary(
        level=level,
        grounded_count=g,
        user_provided_count=u,
        illustrative_count=i,
        ai_proposed_count=a,
        citations=sorted(citations),
    )