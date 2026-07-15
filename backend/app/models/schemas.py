from pydantic import BaseModel, Field
from typing import Literal, Optional


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=3)
    session_id: Optional[str] = None
    upload_mode: Literal["none", "blend", "grounded_only"] = "none"
    include_uploaded: bool = False


class PaperResult(BaseModel):
    title: str
    authors: list[str]
    summary: str
    link: str
    published: Optional[str] = None
    relevance_score: Optional[float] = None


class ChatResponse(BaseModel):
    answer: str
    session_id: str
    papers: list[PaperResult]
    citations: list[str]
    coverage_gaps: list[str] = []
    domain_caveat: Optional[str] = None
    papers_below_threshold: int = 0
    graph_contradictions: list[dict] = []
    graph_entities: list[dict] = []


class FollowupRequest(BaseModel):
    session_id: str
    question: str = Field(..., min_length=3)


class FollowupResponse(BaseModel):
    answer: str
    sources: list[str]


class UploadResponse(BaseModel):
    filename: str
    chunks_indexed: int
    status: str
