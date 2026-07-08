from pydantic import BaseModel, Field
from typing import Literal, Optional


class NormalizedQuery(BaseModel):
    search_term: str = Field(description="Bare technical term/phrase, stripped of conversational framing")
    is_definitional: bool = Field(description="True if user wants foundational/overview understanding, not a narrow variant")


class PaperScore(BaseModel):
    relevance_to_query: float = Field(ge=0, le=1, description="Does the abstract actually address the query topic?")
    foundational_importance: float = Field(ge=0, le=1, description="How central/seminal this paper is to the topic, independent of recency")
    paper_type: Literal["foundational", "survey", "application", "evaluation", "optimization"]
    justification: str = Field(description="1 sentence, must cite a specific detail from the abstract")


class IndexedPaperScore(PaperScore):
    paper_index: int = Field(description="0-based index matching the order papers were listed in the prompt")


class BatchPaperScores(BaseModel):
    scores: list[IndexedPaperScore]


class PaperSummary(BaseModel):
    paper_id: str
    key_contribution: str = Field(description="1-2 sentences: what this paper adds")
    methodology: str = Field(description="1-2 sentences: how they did it")
    findings: str = Field(description="1-2 sentences: what they found")
    relevance_to_query: str = Field(description="1 sentence: why this answers the user's query")


class FinalAnswer(BaseModel):
    answer: str = Field(description="Synthesized answer to the user's query, grounded in the summaries")
    confidence: float = Field(ge=0, le=1)
    papers_used: list[str] = Field(description="paper_ids actually cited in the answer")


class RetryDecision(BaseModel):
    should_retry: bool
    refined_query: Optional[str] = Field(default=None, description="Better search query if retrying")
    reason: str


class PageClassification(BaseModel):
    section_type: Literal[
        "title", "abstract", "toc", "intro", "method",
        "results", "conclusion", "references", "appendix", "other"
    ]
    confidence: float = Field(ge=0, le=1)
