from pydantic import BaseModel, Field
from typing import Literal, Optional


class NormalizedQuery(BaseModel):
    search_terms: list[str] = Field(
        description="5 distinct technical search phrases — one per distinct concept named "
        "in the query. Vary phrasing: use full names, abbreviations, related concepts."
    )
    is_definitional: bool = Field(description="True if user wants foundational/overview understanding, not a narrow variant")
    likely_cs_relevant: bool = Field(
        default=True,
        description="True if arXiv (CS/physics/math preprints) is a sensible source for this query. "
        "False for health, medical, biology, law, social science, business, or other non-CS domains."
    )
    domain_full: Optional[str] = Field(
        default=None,
        description="If the query explicitly mentions a scientific domain (e.g., 'NLP', 'computer vision'), provide its full name (e.g., 'natural language processing', 'computer vision'). Otherwise null."
    )
    domain_keywords: list[str] = Field(
        default_factory=list,
        description="Short keywords/phrases that characterize the domain (e.g. ['language', 'text', 'nlp']). Empty list if no domain specified."
    )
    mandatory_domain_keywords: Optional[list[str]] = Field(
        default=None,
        description="If the query specifies a domain, list 2-3 words that MUST appear in a paper's abstract to be considered relevant. E.g., for NLP: ['language', 'text', 'nlp']. None if no domain."
    )


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
    domain_caveat: Optional[str] = Field(
        default=None,
        description="For health/medical/legal/financial queries: a brief honest note that this is "
        "not verified medical/legal/financial advice and the papers found may not reflect current "
        "clinical/legal consensus."
    )


class RetryDecision(BaseModel):
    should_retry: bool
    refined_query: Optional[str] = Field(default=None, description="Better search query if retrying")
    reason: str


class FollowupAnswer(BaseModel):
    answer: str
    sources_used: list[str] = Field(description="Paper titles that directly informed this answer")
    grounded: bool = Field(description="False if the retrieved chunks don't actually answer the question")


class ClusterSection(BaseModel):
    theme: str = Field(description="Short label for what unites this group of papers")
    content: str = Field(description="3-5 sentences of substantive content about this cluster's papers, with [paper_id] markers on every claim")
    paper_ids: list[str]


class ClusteredFinalAnswer(BaseModel):
    sections: list[ClusterSection]
    overview: str = Field(description="1-2 sentence framing of how these clusters relate to the overall query")
    confidence: float = Field(ge=0, le=1)
    coverage_gaps: list[str] = Field(default_factory=list)
