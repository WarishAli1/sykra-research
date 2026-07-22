from typing import Literal, Optional, TypedDict

class AgentState(TypedDict):
    query: str
    session_id: str
    turn_id: str 
    evidence_mode: Literal["literature", "uploaded", "blended"]
    response_mode: Literal["normal", "researched", "graph_research"]
    refined_query: Optional[str]
    search_terms: list[str]
    search_queries: list[str]
    query_understanding: Optional[dict]
    query_plan: Optional[dict]
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
    low_confidence_results: bool
    uploaded_context: list[dict]
    term_coverage: dict[str, bool]
    papers_below_threshold: int
    final_answer: str
    coverage_gaps: list[str]
    domain_caveat: Optional[str]
    citations: list[str]
    references: list[dict]
    needs_retry: bool
    error: Optional[str]
    validation_results: list[str]
    graph_contradictions: list[dict]
    graph_entities: list[dict]
    conversation_history: list[dict]
    chart_spec_raw: Optional[str]
    chart_url: Optional[str]      
    comparison_table_markdown: Optional[str] 
    comparison_table_caption: Optional[str]  
