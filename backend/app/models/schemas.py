from pydantic import BaseModel, Field, field_validator
from typing import Literal, Optional


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=3)
    session_id: Optional[str] = None
    turn_id: Optional[str] = None
    evidence_mode: Literal["literature", "uploaded", "blended"] = "literature"
    response_mode: Literal["normal", "researched", "graph_research"] = "normal"
    request_id: Optional[str] = None
    conversation_history: list[dict] = Field(default_factory=list)


class PaperResult(BaseModel):
    title: str = "Untitled"
    authors: list[str] = Field(default_factory=list)
    summary: str = ""
    link: str = ""
    published: Optional[str] = None
    relevance_score: Optional[float] = None
    source: str = "unknown"
    is_uploaded: bool = False
    file_url: Optional[str] = None

    @field_validator("source", mode="before")
    @classmethod
    def _normalize_source(cls, v):
        if not v:
            return "unknown"

        primary = str(v).split("+")[0].strip().lower()
        allowed = {
            "arxiv",
            "openalex",
            "user_upload",
            "semanticscholar",
            "semantic_scholar",
            "web",
        }

        if primary == "semantic_scholar":
            return "semanticscholar"

        return primary if primary in allowed else "unknown"

    @field_validator("authors", mode="before")
    @classmethod
    def _normalize_authors(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [v] if v.strip() else []
        return [str(a) for a in v if a]


class ReferenceEntry(BaseModel):
    id: int
    title: str
    authors: list[str] = Field(default_factory=list)
    link: str
    published: Optional[str] = None
    source: str = "unknown"
    source_role: Optional[str] = None
    why_cited: Optional[str] = None
    support_level: Optional[str] = None


class ChatResponse(BaseModel):
    answer: str
    session_id: str
    turn_id: str
    papers: list[PaperResult]
    citations: list[str] = Field(default_factory=list)

    # New disclaimer field
    disclaimer: Optional[str] = None

    papers_below_threshold: int = 0
    graph_contradictions: list[dict] = Field(default_factory=list)
    graph_entities: list[dict] = Field(default_factory=list)
    response_mode: Literal["normal", "researched", "graph_research"] = "normal"
    references: list[ReferenceEntry] = Field(default_factory=list)
    chart_url: Optional[str] = None
    filename: Optional[str] = None
    citation_audit: list[dict] = Field(default_factory=list)
    math_verification: Optional[dict] = None
    primary_source_present: Optional[bool] = None

    report_plan: Optional[dict] = None
    sections: list[dict] = Field(default_factory=list)
    information_needs: list[str] = Field(default_factory=list)
    complexity_score: int = 0
    report_notice: Optional[str] = None


class FollowupRequest(BaseModel):
    session_id: str
    turn_id: Optional[str] = None
    question: str = Field(..., min_length=3)
    response_mode: Literal["normal", "researched", "graph_research"] = "normal"
    request_id: Optional[str] = None


class FollowupResponse(BaseModel):
    answer: str
    sources: list[str] = Field(default_factory=list)
    references: list[ReferenceEntry] = Field(default_factory=list)
    chart_url: Optional[str] = None


class RegenerateRequest(BaseModel):
    session_id: str
    turn_id: Optional[str] = None
    query: str = Field(..., min_length=3)
    response_mode: Literal["normal", "researched", "graph_research"] = "normal"
    evidence_mode: Literal["literature", "uploaded", "blended"] = "literature"
    is_followup: bool = False
    upload_mode: Literal["none", "blend", "grounded_only"] = "none"
    include_uploaded: bool = False


class UploadResponse(BaseModel):
    filename: str
    chunks_indexed: int
    status: str
    file_url: str
    link: str


class PdfExportRequest(BaseModel):
    session_id: str
    format: Literal["latex", "standard"] = "standard"
    turn_id: Optional[str] = None
    title: Optional[str] = None
    answer: str
    references: list[ReferenceEntry] = Field(default_factory=list)
    chart_path: Optional[str] = None


class FilenameResponse(BaseModel):
    turn_id: str
    filename: Optional[str] = None


ChatResponse.model_rebuild()