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
    term_coverage: dict[str, dict]
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
    needs_revision: bool
    revision_count: int
    revision_instruction: Optional[str]
    revision_section_ids: list[str]
    _request_id: str
    _streaming_enabled: bool
    _cancel_check: Optional[any]
    report_plan: Optional[dict]
    information_needs: list[str]
    complexity_score: int
    report_depth: Literal["low", "medium", "high"]
    target_word_count: int
    module_plan: list[dict]
    module_evidence_map: dict[str, dict]
    section_outputs: list[dict]
    dynamic_confidence: Optional[dict]
    cited_paper_ids: list[str]
    report_notice: Optional[str]
    verification_status: str
    epistemic_mode: Optional[
        Literal[
            "research_synthesis",
            "textbook_derivation",
            "conceptual_explanation",
            "decision_support",
        ]
    ]
    query_embedding: Optional[list[float]]
    target_paper_k: int
    preview_answer: Optional[str]
    preview_streamed: bool
    search_cache_hit: bool
    answer_spec: Optional[dict]
    source_plan: Optional[dict]
    retrieval_plan: Optional[dict]
    evidence_matrix: dict[str, dict]
    citation_audit: list[dict]
    math_verification: Optional[dict]
    primary_source_present: bool
    reasoning_ledger: Optional[dict]
    epistemic_report: Optional[dict]

    evidence_contract: Optional[dict]
    research_subquestions: list[dict]
    evidence_coverage_matrix: list[dict]
    evidence_sufficiency: Optional[dict]
    eligible_papers: list[dict]
    background_papers: list[dict]
    ineligible_papers: list[dict]