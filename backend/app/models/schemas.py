from pydantic import BaseModel, Field
from typing import Literal, Optional

class ChatRequest(BaseModel):
    query: str = Field(..., min_length=3)
    session_id: Optional[str] = None
    turn_id: Optional[str] = None
    evidence_mode: Literal["literature", "uploaded", "blended"] = "literature"
    response_mode: Literal["normal", "researched", "graph_research"] = "normal"
    request_id: Optional[str] = None
    conversation_history: list[dict] = []

class PaperResult(BaseModel):
    title: str
    authors: list[str]
    summary: str
    link: str
    published: Optional[str] = None
    relevance_score: Optional[float] = None
    source: Literal["arxiv", "openalex", "user_upload", "unknown"] = "unknown"
    is_uploaded: bool = False
    file_url: Optional[str] = None

class ChatResponse(BaseModel):
    answer: str
    session_id: str
    turn_id: str
    papers: list[PaperResult]
    citations: list[str]
    coverage_gaps: list[str] = []
    domain_caveat: Optional[str] = None
    papers_below_threshold: int = 0
    graph_contradictions: list[dict] = []
    graph_entities: list[dict] = []
    response_mode: Literal["normal", "researched", "graph_research"] = "normal"
    references: list["ReferenceEntry"] = []
    chart_url: Optional[str] = None
    filename: Optional[str] = None

class ReferenceEntry(BaseModel):
    id: int
    title: str
    authors: list[str]
    link: str
    published: Optional[str] = None
    source: str = "unknown"

class FollowupRequest(BaseModel):
    session_id: str
    turn_id: Optional[str] = None
    question: str = Field(..., min_length=3)
    response_mode: Literal["normal", "researched", "graph_research"] = "normal"
    request_id: Optional[str] = None

class FollowupResponse(BaseModel):
    answer: str
    sources: list[str]
    references: list[ReferenceEntry] = []
    chart_url: Optional[str] = None

class RegenerateRequest(BaseModel):
    session_id: str
    turn_id: Optional[str] = None
    query: str = Field(..., min_length=3)
    response_mode: Literal["normal", "researched", "graph_research"] = "normal"
    is_followup: bool = False
    evidence_mode: Literal["literature", "uploaded", "blended"] = "literature"

class RegenerateRequest(BaseModel):
    session_id: str
    turn_id: Optional[str] = None
    query: str = Field(..., min_length=3)
    response_mode: Literal["normal", "researched", "graph_research"] = "normal"
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
    references: list[ReferenceEntry] = []
    chart_path: Optional[str] = None

class FilenameResponse(BaseModel):
    turn_id: str
    filename: Optional[str] = None

ChatResponse.model_rebuild()