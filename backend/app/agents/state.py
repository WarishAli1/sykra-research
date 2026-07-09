from typing import TypedDict, Optional


class AgentState(TypedDict):
    query: str
    use_uploaded_only: bool

    refined_query: Optional[str]
    search_terms: list[str]
    is_definitional: bool
    search_attempts: int
    max_search_attempts: int

    raw_search_results: list[dict]
    extracted_papers: list[dict]
    ranked_papers: list[dict]
    summaries: dict[str, dict]

    final_answer: str
    coverage_gaps: list[str]
    citations: list[str]

    needs_retry: bool
    error: Optional[str]
    validation_results: list[str]
