from pydantic import BaseModel, Field
from typing import Literal, Optional, List

class NormalAnswer(BaseModel):
    direct_answer: str = Field(description="2-4 sentence direct answer to the user's question.")
    brief_context: Optional[str] = Field(default=None, description="EXACTLY ONE sentence explaining essential concepts ONLY if strictly necessary.")
    evidence: str = Field(description="Detailed summary of 2-4 key studies. For each study, explicitly cover: what it proposed, how it was evaluated, datasets used, main findings, and why it matters. If only one study exists, explain it in depth. Use markdown formatting (e.g., bolding study names).")
    limitations: list[str] = Field(description="Expanded list of limitations. Must include specific methodological gaps such as: lack of replication, absence of user studies, limited benchmarks, lack of comparison with other techniques, or uncertain generalizability. Provide at least 3-5 distinct points.")
    conclusion: str = Field(description="Briefly answer these three questions: 1) What is supported by evidence? 2) What remains uncertain? 3) What should future work investigate?")
    confidence: Literal["High", "Medium", "Low"] = Field(description="Confidence in the answer. High = multiple direct studies. Medium = only 1 direct study. Low = no direct studies/indirect evidence.")
    confidence_explanation: str = Field(description="Brief explanation of the confidence level based on the evidence.")
    references: list[str] = Field(description="paper_ids of the 1-3 most relevant papers.")

class ResearchAnswer(BaseModel):
    executive_summary: str = Field(description="High-level summary of what the literature supports, what is uncertain, and the final answer.")
    background_concepts: str = Field(description="Explanation of relevant concepts from general to specific. Teach before evaluating.")
    related_research: str = Field(description="Brief coverage of adjacent areas and explanation of their relevance to the query.")
    literature_review: str = Field(description="Synthesized summary of key papers (methods, datasets, metrics, findings). Synthesize, do not just list.")
    comparative_analysis: Optional[str] = Field(default=None, description="Comparison of methods, datasets, or findings. Can be formatted as a markdown table if helpful.")
    evidence_assessment: str = Field(description="Strength, consistency, and limitations of the current evidence.")
    research_gaps: str = Field(description="Genuine unanswered questions or missing areas in the literature.")
    practical_implications: str = Field(description="Actionable implications and real-world applications, separating evidence from speculation.")
    final_answer: str = Field(description="The definitive, synthesized answer to the user's original question.")
    confidence: Literal["High", "Medium", "Low"] = Field(description="Confidence level based on evidence quality/quantity.")
    confidence_explanation: str = Field(description="Brief explanation based on evidence quality/quantity.")
    references: list[str] = Field(description="paper_ids of high-quality relevant papers.")

class QueryUnderstanding(BaseModel):
    main_topic: str = Field(description="The core research topic")
    subtopics: list[str] = Field(description="Important subtopics or facets")
    objectives: list[str] = Field(description="Research objectives or goals")
    methods_techniques: list[str] = Field(description="Methods, algorithms, models, and techniques")
    application_domain: str = Field(description="The specific application domain")
    acronyms: dict[str, str] = Field(description="Acronyms and their expanded forms")
    entities: list[str] = Field(description="Important entities, datasets, or frameworks")
    academic_terminology: list[str] = Field(description="Academic terminology commonly used in literature for this topic")

class QueryPlan(BaseModel):
    rewritten_queries: list[str] = Field(description="2-3 semantically equivalent queries using academic phrasing")
    expanded_queries: list[str] = Field(description="2-3 broader/narrower/related concepts to improve recall")
    method_queries: list[str] = Field(description="1-2 queries focusing on specific algorithms/techniques")
    domain_queries: list[str] = Field(description="1-2 queries focusing on the application domain")
    fallback_queries: list[str] = Field(description="1-2 very broad queries if the topic is too narrow")

# Keep existing schemas for backward compatibility
class NormalizedQuery(BaseModel):
    search_terms: list[str] = Field(description="5 distinct technical search phrases")
    is_definitional: bool = Field(description="True if user wants foundational understanding")
    likely_cs_relevant: bool = Field(default=True, description="True if arXiv is sensible source")
    domain_full: Optional[str] = Field(default=None)
    domain_keywords: list[str] = Field(default_factory=list)
    mandatory_domain_keywords: Optional[list[str]] = Field(default=None)

class PaperSummaryItem(BaseModel):
    paper_id: str
    key_contribution: str
    methodology: str
    findings: str
    relevance_to_query: str
    evidence_type: Literal["direct", "supporting", "background"] = Field(default="supporting")

class BatchPaperSummaries(BaseModel):
    summaries: list[PaperSummaryItem]

class FinalAnswer(BaseModel):
    answer: str
    confidence: float
    papers_used: list[str]
    coverage_gaps: list[str] = Field(default_factory=list)
    domain_caveat: Optional[str] = Field(default=None)

class RetryDecision(BaseModel):
    should_retry: bool
    refined_query: Optional[str] = Field(default=None)
    reason: str

class FollowupAnswer(BaseModel):
    answer: str
    sources_used: list[str]
    grounded: bool

class ClusterSection(BaseModel):
    theme: str
    content: str
    paper_ids: list[str]

class ClusteredFinalAnswer(BaseModel):
    sections: list[ClusterSection]
    overview: str
    confidence: float
    coverage_gaps: list[str] = Field(default_factory=list)
