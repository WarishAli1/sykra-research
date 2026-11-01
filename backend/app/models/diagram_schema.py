from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


DiagramType = Literal["flowchart", "dfd", "architecture"]
NodeType = Literal[
    "start", "process", "decision", "data", "end",
    "external", "store", "client", "service", "database", "boundary", "note",
]


class DiagramNodeDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100)
    type: NodeType = "process"
    position: dict[str, float]
    label: str = Field(default="Untitled", max_length=500)
    parentId: str | None = Field(default=None, min_length=1, max_length=100)
    style: dict[str, str] | None = None


class DiagramEdgeDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100)
    source: str = Field(min_length=1, max_length=100)
    target: str = Field(min_length=1, max_length=100)
    label: str | None = Field(default=None, max_length=200)
    type: str | None = Field(default=None, max_length=40)
    protocol: str | None = Field(default=None, max_length=40)


class DiagramPageDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    diagramType: DiagramType = "flowchart"
    nodes: list[DiagramNodeDocument] = Field(default_factory=list)
    edges: list[DiagramEdgeDocument] = Field(default_factory=list)


class DiagramDocumentModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schemaVersion: Literal[1, 2] = 2
    id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    pages: list[DiagramPageDocument] = Field(min_length=1)
    activePageId: str = Field(min_length=1, max_length=100)
    updatedAt: str
    dismissedIssues: list[str] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def active_page_exists(self):
        if self.activePageId not in {page.id for page in self.pages}:
            raise ValueError("activePageId must reference a page")
        return self
