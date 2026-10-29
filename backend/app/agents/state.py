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
    method_note: Optional[str]
    max_search_attempts: int
    raw_search_results: list[dict]
    extracted_papers: list[dict]
    ranked_papers: list[dict]
    summaries: dict[str, dict]
    low_confidence_results: bool
    uploaded_context: list[dict]
    document_map: Optional[str]
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
    original_query: Optional[str]
    is_followup: bool
    previous_papers: list[dict]
    output_instruction: Optional[str]
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

    report_mode_enabled: bool
    report_type: Optional[str]
    report_audience: Optional[str]
    report_title: Optional[str]
    report_language: Optional[str]
    report_mode_plan: Optional[dict]
    report_section_plan: list[dict]
    report_source_records: list[dict]
    report_derived_values: list[dict]
    report_discrepancies: list[dict]
    report_validation_results: Optional[dict]
    report_warnings: list[dict]
    report_revision_count: int
    confirmed_source_records: Optional[list[dict]] 
    report_claims: list[dict]
    report_claim_summary: Optional[dict]
    report_section_confidence: dict[str, str]  
    report_brief: Optional[dict]
    report_section_contracts: list[dict]
    report_execution_path: Optional[str]
    report_title_user_supplied: bool
    evidence_ledger: list[dict]
    evidence_gaps: list[str]
    report_evidence_attempts: int
    report_evidence_retry: bool
    report_evidence_gap_queries: list[str]
    report_editorial_done: bool
    report_claim_verify_done: bool
    report_revision_tickets: list[dict]
    report_revision_tickets: list[dict]
    report_structure_approved: bool
    report_structure_draft: Optional[dict]
    report_guideline_text: Optional[str]