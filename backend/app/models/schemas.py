from pydantic import BaseModel, Field
from typing import Optional

class ChatRequest(BaseModel):
    query: str = Field(..., min_length=3)
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
    papers: list[PaperResult]
    citations: list[str]
    coverage_gaps: list[str] = []

class UploadResponse(BaseModel):
    filename: str
    chunks_indexed: int
    status: str

class CompareRequest(BaseModel):
    paper_ids: list[str] = Field(..., min_length=2, max_length=5)
