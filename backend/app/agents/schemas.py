from pydantic import BaseModel, Field
from typing import Literal, Optional


class NormalizedQuery(BaseModel):
    search_terms: list[str] = Field(
        description="1-3 distinct technical search terms — one per distinct concept named "
        "in the query. If the query is about a single concept, return just one term."
    )
    is_definitional: bool = Field(description="True if user wants foundational/overview understanding, not a narrow variant")


class PaperSummaryItem(BaseModel):
    paper_id: str
    key_contribution: str
    methodology: str
    findings: str
    relevance_to_query: str


class BatchPaperSummaries(BaseModel):
    summaries: list[PaperSummaryItem]


class FinalAnswer(BaseModel):
    answer: str = Field(description="Synthesized answer to the user's query, grounded in the summaries")
    confidence: float = Field(ge=0, le=1)
    papers_used: list[str] = Field(description="paper_ids actually cited in the answer")
    coverage_gaps: list[str] = Field(
        default_factory=list,
        description="Named concepts from the query with little/no dedicated source material found — "
        "state this honestly instead of silently substituting adjacent content."
    )


class RetryDecision(BaseModel):
    should_retry: bool
    refined_query: Optional[str] = Field(default=None, description="Better search query if retrying")
    reason: str
