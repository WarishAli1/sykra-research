from pydantic import BaseModel, Field
from typing import Optional


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=3)
    session_id: Optional[str] = None
    use_uploaded_only: bool = False


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


class CompareRequest(BaseModel):
    session_id: str
    paper_titles: list[str] = Field(..., min_length=2, max_length=5, description="Titles of papers already seen in this session")
    aspects: Optional[list[str]] = Field(default=None, description="Optional specific aspects to compare. If omitted, the system picks sensible defaults.")


class ComparisonAspectOut(BaseModel):
    aspect: str
    paper_values: dict[str, str]


class PaperComparisonOut(BaseModel):
    aspects: list[ComparisonAspectOut]
    overview: str
    recommendation: Optional[str] = None
    papers_compared: list[str]


class CompareResponse(BaseModel):
    comparison: PaperComparisonOut


class CitationExportRequest(BaseModel):
    session_id: str
    style: str = "apa"
    paper_titles: Optional[list[str]] = None


class CitationExportResponse(BaseModel):
    style: str
    citations: list[str]
