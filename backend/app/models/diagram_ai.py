from typing import Literal

from pydantic import BaseModel, Field

from app.models.diagram_schema import DiagramDocumentModel, DiagramType, NodeType


class AiDiagramNode(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    type: NodeType
    label: str = Field(min_length=1, max_length=200)


class AiDiagramEdge(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    source: str = Field(min_length=1, max_length=80)
    target: str = Field(min_length=1, max_length=80)
    label: str | None = Field(default=None, max_length=200)
    type: str | None = Field(default=None, max_length=40)


class AiDiagramOutput(BaseModel):
    diagram_type: DiagramType
    title: str = Field(min_length=1, max_length=200)
    nodes: list[AiDiagramNode] = Field(max_length=100)
    edges: list[AiDiagramEdge] = Field(max_length=200)


class DiagramAiGenerateRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=200)
    diagram_type: DiagramType
    instruction: str = Field(min_length=3, max_length=4000)


class DiagramAiEditRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=200)
    document: DiagramDocumentModel
    instruction: str = Field(min_length=3, max_length=2000)


class DiagramPatch(BaseModel):
    op: Literal["add_node", "update_node", "remove_node", "add_edge", "update_edge", "remove_edge"]
    id: str = Field(min_length=1, max_length=80)
    value: dict | None = None


class DiagramAiEditOutput(BaseModel):
    patches: list[DiagramPatch] = Field(max_length=100)
