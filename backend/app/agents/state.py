from typing import Literal, Optional, TypedDict


class AgentState(TypedDict):
    query: str
    session_id: str
    include_uploaded: bool
    upload_mode: Literal["none", "blend", "grounded_only"]

    refined_query: Optional[str]
    search_terms: list[str]
    is_definitional: bool
    likely_cs_relevant: bool
    domain_full: Optional[str]
    domain_keywords: list[str]
    mandatory_domain_keywords: Optional[list[str]]
    search_attempts: int
    max_search_attempts: int

    raw_search_results: list[dict]
    extracted_papers: list[dict]
    ranked_papers: list[dict]
    summaries: dict[str, dict]

    uploaded_context: list[dict]

    term_coverage: dict[str, bool]
    papers_below_threshold: int

    final_answer: str
    coverage_gaps: list[str]
    domain_caveat: Optional[str]
    citations: list[str]

    needs_retry: bool
    error: Optional[str]
    validation_results: list[str]

    graph_contradictions: list[dict]
    graph_entities: list[dict]
