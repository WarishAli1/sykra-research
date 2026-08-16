from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator
from typing import Any, Literal, Optional, List


def _normalize_string_list(v: Any) -> List[str]:
    if v is None:
        return []

    if isinstance(v, str):
        return [v] if v.strip() else []

    if isinstance(v, list):
        return [str(x) for x in v if x is not None]

    return []


def _normalize_int_list(v: Any) -> List[int]:
    if v is None:
        return []

    if isinstance(v, (int, float)):
        return [int(v)]

    if isinstance(v, str):
        try:
            return [int(v)]
        except ValueError:
            return []

    if isinstance(v, list):
        out: List[int] = []

        for x in v:
            try:
                out.append(int(x))
            except (ValueError, TypeError):
                pass

        return out

    return []


def _first_present(data: dict, keys: tuple[str, ...]) -> Any:
    """
    Return the first non-None value found in `data` for the given keys.

    This is used for alias normalization only.
    It must NOT create defaults for missing required semantic fields.
    """
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]

    return None


class AnswerRequirement(BaseModel):
    id: str
    text: str

    kind: Literal[
        "definition",
        "mechanism",
        "architecture",
        "derivation",
        "comparison",
        "historical_origin",
        "evaluation",
        "implementation",
        "limitation",
        "application",
        "background",
    ] = "background"

    weight: int = Field(default=1, ge=1, le=3)
    must_cite: bool = False
    requires_primary_source: bool = False


class CanonicalEntity(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)

    expected_primary_source: Optional[str] = None
    expected_authors: list[str] = Field(default_factory=list)
    expected_year: Optional[int] = None

    reason: Optional[str] = None


class EvidenceConstraint(BaseModel):
    field: Literal[
        "publication_year",
        "study_type",
        "population",
        "intervention",
        "comparator",
        "outcome",
        "geography",
        "language",
        "sample_size",
        "follow_up_duration",
    ] = "publication_year"
    operator: Literal[
        "eq", "neq", "gt", "lt", "gte", "lte", "in", "contains", "range",
    ] = "gte"
    value: Any = None
    strength: Literal["hard", "preferred", "optional"] = "preferred"
    description: str = ""


class EvidenceContract(BaseModel):
    constraints: list[EvidenceConstraint] = Field(default_factory=list)
    analytical_requirements: list[str] = Field(default_factory=list)
    evidence_hierarchy: list[str] = Field(default_factory=list)
    required_output_sections: list[str] = Field(default_factory=list)
    minimum_evidence_count: int = 3
    consensus_required: bool = False
    primary_source_required: bool = False

    def hard_constraints(self) -> list[EvidenceConstraint]:
        return [c for c in self.constraints if c.strength == "hard"]

    def preferred_constraints(self) -> list[EvidenceConstraint]:
        return [c for c in self.constraints if c.strength == "preferred"]


class ResearchSubQuestion(BaseModel):
    id: str = ""
    text: str = ""
    contract: EvidenceContract = Field(default_factory=EvidenceContract)
    status: Literal[
        "pending", "researching", "answered", "insufficient_evidence",
    ] = "pending"
    coverage_score: float = 0.0


class AnswerSpec(BaseModel):
    question_types: list[
        Literal[
            "factual",
            "conceptual",
            "technical_explanation",
            "mathematical_derivation",
            "comparison",
            "literature_review",
            "implementation",
            "clinical",
            "legal",
            "financial",
            "scientific",
            "decision_support",
        ]
    ] = Field(default_factory=list)
    domain: str = ""
    answer_intent: str = ""
    requirements: list[AnswerRequirement] = Field(default_factory=list)
    canonical_entities: list[CanonicalEntity] = Field(default_factory=list)

    @field_validator("canonical_entities", mode="before")
    @classmethod
    def _normalize_canonical_entities(cls, v: Any) -> Any:
        if not isinstance(v, list):
            return v
        out = []
        for item in v:
            if isinstance(item, str):
                out.append({"name": item.strip()})
            elif isinstance(item, dict):
                if "name" not in item:
                    for key in ("text", "entity", "title", "value"):
                        if key in item:
                            item["name"] = item[key]
                            break
                out.append(item)
            else:
                out.append(item)
        return out

    foundational_papers: list[dict] = Field(default_factory=list) 
    primary_source_required: bool = False
    equation_verification_required: bool = False
    expected_equations: list[str] = Field(default_factory=list)
    expected_components: list[str] = Field(default_factory=list)
    non_goals: list[str] = Field(default_factory=list)
    answer_outline: list[str] = Field(default_factory=list)
    retrieval_focus: list[str] = Field(default_factory=list)
    exact_search_queries: list[str] = Field(default_factory=list)

    quantitative_required: bool = False
    scenario_analysis_required: bool = False
    required_quantitative_variables: list[str] = Field(default_factory=list)
    scenario_dimensions: list[str] = Field(default_factory=list)
    required_source_tiers: list[str] = Field(default_factory=list)
    epistemic_abstention_triggers: list[str] = Field(default_factory=list)

    evidence_contract: EvidenceContract = Field(default_factory=EvidenceContract)
    research_subquestions: list[ResearchSubQuestion] = Field(default_factory=list)
    difficulty_level: int = Field(default=3, ge=1, le=5)
    domain_evidence_policy: str = "general"




class RetrievalIntent(BaseModel):
    query: str

    purpose: Literal[
        "canonical_source",
        "requirement",
        "equation",
        "comparison",
        "official_documentation",
        "freshness",
        "background",
    ] = "requirement"

    priority: int = Field(default=1, ge=1, le=3)

    source_capabilities: list[str] = Field(default_factory=list)


class RetrievalPlan(BaseModel):
    intents: list[RetrievalIntent] = Field(default_factory=list)

    primary_source_required: bool = False
    freshness_required: bool = False

    use_foundational_search: bool = False
    use_citation_backtracking: bool = False

    max_search_intents: int = Field(default=4, ge=1, le=6)


class PaperJudgment(BaseModel):
    paper_id: int

    answers_question: float = Field(ge=0, le=1)
    primary_source_fit: float = Field(ge=0, le=1)

    requirement_coverage: List[str] = Field(default_factory=list)

    source_role: Literal[
        "primary",
        "secondary",
        "survey",
        "application",
        "background",
        "irrelevant",
    ] = "background"

    reason: str = ""

    @model_validator(mode="before")
    @classmethod
    def _normalize_aliases(cls, data: Any) -> Any:
        """
        Normalize common LLM aliases BEFORE field validation.

        Important:
        - This does NOT invent missing required values.
        - If neither the canonical field nor an alias is present,
          Pydantic validation will fail, which is intentional.
        """
        if not isinstance(data, dict):
            return data

        out = dict(data)

        if "paper_id" not in out or out.get("paper_id") is None:
            alias = _first_present(out, ("id", "index", "paper_index"))
            if alias is not None:
                out["paper_id"] = alias

        if "answers_question" not in out or out.get("answers_question") is None:
            alias = _first_present(
                out,
                (
                    "answer_relevance",
                    "relevance",
                    "relevance_score",
                    "question_relevance",
                    "support_score",
                    "overall_score",
                    "score",
                    "fit",
                ),
            )
            if alias is not None:
                out["answers_question"] = alias

        if "primary_source_fit" not in out or out.get("primary_source_fit") is None:
            alias = _first_present(
                out,
                (
                    "primary_fit",
                    "primary_score",
                    "primary_source_score",
                    "canonical_fit",
                    "origin_fit",
                ),
            )
            if alias is not None:
                out["primary_source_fit"] = alias

        if "requirement_coverage" not in out or out.get("requirement_coverage") is None:
            alias = _first_present(
                out,
                (
                    "requirements",
                    "requirement_ids",
                    "coverage",
                ),
            )
            if alias is not None:
                out["requirement_coverage"] = alias

        if "source_role" not in out or out.get("source_role") is None:
            alias = _first_present(out, ("role", "source_type"))
            if alias is not None:
                out["source_role"] = alias

        return out

    @field_validator("requirement_coverage", mode="before")
    @classmethod
    def _normalize_requirement_coverage(cls, v: Any) -> List[str]:
        return _normalize_string_list(v)


class AnswerClaim(BaseModel):
    id: str = ""
    text: str = ""

    claim_type: Literal[
        "historical_origin",
        "definition",
        "equation",
        "mechanism",
        "comparison",
        "empirical_result",
        "limitation",
        "application",
        "inference",
    ] = "definition"

    cited_paper_ids: List[int] = Field(default_factory=list)
    requires_primary_source: bool = False

    @field_validator("cited_paper_ids", mode="before")
    @classmethod
    def _normalize_cited_paper_ids(cls, v: Any) -> List[int]:
        return _normalize_int_list(v)


class CitationAudit(BaseModel):
    claim_id: str
    claim_text: str = ""
    citation_valid: bool = False
    support_level: Literal[
        "direct",
        "derived",
        "supported",
        "background",
        "unsupported",
    ] = "unsupported"
    source_role: Literal[
        "primary",
        "secondary",
        "survey",
        "application",
        "background",
        "none",
    ] = "none"
    reason: str = ""
    corrected_citation_paper_id: Optional[int] = None
    is_quantitative: bool = False
    epistemic_status: Literal[
        "verified",    
        "uncertain",   
        "unknown",      
        "unsupported", 
    ] = "unsupported"


class EquationCheck(BaseModel):
    original_text: str = ""
    canonical_form: Optional[str] = None

    is_correct: bool = True

    issues: List[str] = Field(default_factory=list)
    corrected_form: Optional[str] = None
    explanation: str = ""

    @field_validator("issues", mode="before")
    @classmethod
    def _normalize_issues(cls, v: Any) -> List[str]:
        return _normalize_string_list(v)


class MathVerification(BaseModel):
    checked_equations: List[EquationCheck] = Field(
        default_factory=list,
        validation_alias=AliasChoices(
            "checked_equations",
            "equation_checks",
            "checks",
            "equations",
            "checked_equation",
            "equation_check",
        ),
    )
    critical_math_failed: bool = False
    notes: str = ""

    @field_validator("checked_equations", mode="before")
    @classmethod
    def _normalize_checked_equations(cls, v: Any) -> Any:
        if isinstance(v, dict):
            return [v]
        if isinstance(v, (list, tuple)):
            return [item for item in v if item is not None]
        return v

    @model_validator(mode="after")
    def _promote_failed_equations(self) -> "MathVerification":
        if not self.critical_math_failed:
            self.critical_math_failed = any(
                eq.is_correct is False for eq in self.checked_equations
            )
        return self


class ComparisonRow(BaseModel):
    dimension: str = Field(
        description="The comparison dimension/axis, e.g. 'Time complexity'"
    )

    values: list[str] = Field(
        description=(
            "One short factual cell value per column, in the same order as "
            "ComparisonTable.columns"
        )
    )


class ComparisonTable(BaseModel):
    applicable: bool = Field(
        description=(
            "True unless the query genuinely has no multi-item comparison structure. "
            "Should be true in almost all cases where >=2 candidate items were provided."
        )
    )

    caption: str = Field(default="Comparison", description="Short table title")

    columns: list[str] = Field(
        default_factory=list,
        description="2-5 named items being compared",
    )

    rows: list[ComparisonRow] = Field(
        default_factory=list,
        description="3-8 comparison dimensions",
    )


class NormalAnswer(BaseModel):
    direct_answer: str = Field(
        description="2-4 sentence direct answer to the user's question."
    )

    brief_context: Optional[str] = Field(
        default=None,
        description=(
            "EXACTLY ONE sentence explaining essential concepts ONLY if strictly necessary."
        ),
    )

    evidence: str = Field(
        description=(
            "Detailed summary of 2-4 key studies. For each study, explicitly cover: "
            "what it proposed, how it was evaluated, datasets used, main findings, and why it matters. "
            "If only one study exists, explain it in depth. Use markdown formatting."
        )
    )

    limitations: list[str] = Field(
        description=(
            "Expanded list of limitations. Must include specific methodological gaps such as: "
            "lack of replication, absence of user studies, limited benchmarks, lack of comparison "
            "with other techniques, or uncertain generalizability. Provide at least 3-5 distinct points."
        )
    )

    conclusion: str = Field(
        description=(
            "Briefly answer these three questions: "
            "1) What is supported by evidence? "
            "2) What remains uncertain? "
            "3) What should future work investigate?"
        )
    )

    confidence: Literal["High", "Medium", "Low"] = Field(
        description="Confidence in the answer."
    )

    confidence_explanation: str = Field(
        description="Brief explanation of the confidence level."
    )

    references: list[str] = Field(
        description="paper_ids of the 1-3 most relevant papers."
    )


class ResearchAnswer(BaseModel):
    executive_summary: str = Field(
        description=(
            "High-level summary of what the literature supports, what is uncertain, "
            "and the final answer."
        )
    )

    background_concepts: str = Field(
        description="Explanation of relevant concepts from general to specific."
    )

    related_research: str = Field(
        description=(
            "Brief coverage of adjacent areas and explanation of their relevance to the query."
        )
    )

    literature_review: str = Field(
        description="Synthesized summary of key papers. Synthesize, do not just list."
    )

    comparative_analysis: Optional[str] = Field(
        default=None,
        description="Comparison of methods, datasets, or findings.",
    )

    evidence_assessment: str = Field(
        description="Strength, consistency, and limitations of the current evidence."
    )

    research_gaps: str = Field(
        description="Genuine unanswered questions or missing areas in the literature."
    )

    practical_implications: str = Field(
        description="Actionable implications and real-world applications."
    )

    final_answer: str = Field(
        description="The definitive, synthesized answer to the user's original question."
    )

    confidence: Literal["High", "Medium", "Low"] = Field(
        description="Confidence level based on evidence quality/quantity."
    )

    confidence_explanation: str = Field(
        description="Brief explanation based on evidence quality/quantity."
    )

    references: list[str] = Field(
        description="paper_ids of high-quality relevant papers."
    )


class QueryUnderstanding(BaseModel):
    main_topic: str = Field(description="The core research topic")
    subtopics: list[str] = Field(description="Important subtopics or facets")
    objectives: list[str] = Field(description="Research objectives or goals")

    methods_techniques: list[str] = Field(
        description="Methods, algorithms, models, and techniques"
    )

    application_domain: str = Field(description="The specific application domain")
    acronyms: dict[str, str] = Field(description="Acronyms and their expanded forms")
    entities: list[str] = Field(description="Important entities, datasets, or frameworks")

    academic_terminology: list[str] = Field(
        description="Academic terminology commonly used in literature for this topic"
    )


class QueryPlan(BaseModel):
    rewritten_queries: list[str] = Field(
        description="2-3 semantically equivalent queries using academic phrasing"
    )

    expanded_queries: list[str] = Field(
        description="2-3 broader/narrower/related concepts to improve recall"
    )

    method_queries: list[str] = Field(
        description="1-2 queries focusing on specific algorithms/techniques"
    )

    domain_queries: list[str] = Field(
        description="1-2 queries focusing on the application domain"
    )

    fallback_queries: list[str] = Field(
        description="1-2 very broad queries if the topic is too narrow"
    )


class NormalizedQuery(BaseModel):
    search_terms: list[str] = Field(description="5 distinct technical search phrases")

    is_definitional: bool = Field(
        description="True if user wants foundational understanding"
    )

    likely_cs_relevant: bool = Field(
        default=True,
        description="True if arXiv is sensible source",
    )

    domain_full: Optional[str] = Field(default=None)
    domain_keywords: list[str] = Field(default_factory=list)
    mandatory_domain_keywords: Optional[list[str]] = Field(default=None)


class PaperSummaryItem(BaseModel):
    paper_id: str
    key_contribution: str
    methodology: str
    findings: str
    relevance_to_query: str

    evidence_type: Literal["direct", "supporting", "background"] = Field(
        default="supporting"
    )

    key_metrics: list[str] = Field(
        default_factory=list,
        description=(
            "Any exact numeric figures explicitly stated in the paper's abstract/text "
            "relevant to comparing methods. Copy numbers verbatim from the source text. "
            "Leave empty if no such figures are stated."
        ),
    )


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


class PlannedModule(BaseModel):
    module_id: str = Field(description="Module id from the module library")
    importance: int = Field(default=50, ge=0, le=100)
    reason: Optional[str] = Field(default=None)


class ReportPlanLLM(BaseModel):
    primary_intent: Literal[
        "explain",
        "compare",
        "research",
        "decision",
        "design",
        "forecast",
        "strategy",
        "troubleshooting",
        "planning",
        "tutorial",
        "coding",
        "mathematical",
        "medical",
        "legal",
        "scientific",
        "mixed",
    ] = "research"

    secondary_intents: list[str] = Field(default_factory=list)

    information_needs: list[str] = Field(
        default_factory=list,
        description=(
            "Atomic information needs, e.g. background, mechanism, comparison, risk, "
            "cost, implementation, forecast, evidence, recommendation."
        ),
    )

    complexity_score: int = Field(default=50, ge=0, le=100)
    depth: Literal["low", "medium", "high"] = Field(default="medium")

    reference_policy: Literal[
        "minimal",
        "standard",
        "research",
        "documentation",
        "none",
    ] = "standard"

    reasoning_policy: Literal[
        "evidence_only",
        "evidence_plus_analysis",
        "first_principles_allowed",
        "speculative_allowed",
    ] = "evidence_plus_analysis"

    domain_guardrails: list[str] = Field(default_factory=list)
    modules: list[PlannedModule] = Field(default_factory=list)
    latency_notice: Optional[str] = Field(default=None)


class SectionOutput(BaseModel):
    module_id: str
    title: str
    content: str

    cited_paper_ids: list[int] = Field(
        default_factory=list,
        description=(
            "The integer N from each [paper_id=N] marker cited in this section's content. "
            "Plain integers, e.g. [0, 2, 5] — not quoted strings."
        ),
    )

    evidence_status: Literal[
        "strong",
        "mixed",
        "weak",
        "none",
        "not_applicable",
    ] = "none"

    confidence: Literal["high", "medium", "low"] = "medium"


class SectionBatch(BaseModel):
    sections: list[SectionOutput]


class DynamicConfidence(BaseModel):
    evidence_quality: Literal["high", "medium", "low"]
    answer_confidence: Literal["high", "medium", "low"]

    prediction_confidence: Optional[Literal["high", "medium", "low"]] = None
    recommendation_confidence: Optional[Literal["high", "medium", "low"]] = None

    data_completeness: Literal["high", "medium", "low"]
    uncertainty: Literal["low", "moderate", "high"]

    explanation: str


class ReportCoverageCheck(BaseModel):
    fully_covers_query: bool = Field(
        description=(
            "True if every specific detail/constraint in the user's query and every required "
            "planned module is addressed or explicitly flagged as unavailable."
        )
    )

    missing_or_assumed: list[str] = Field(default_factory=list)
    missing_modules: list[str] = Field(default_factory=list)
    revision_instruction: str = Field(default="")


class ExtractedVariable(BaseModel):
    name: str = ""
    value: str = ""
    unit: str = ""
    source_paper_id: int = 0
    year: str = ""
    confidence: Literal["high", "medium", "low"] = "medium"


class ScenarioRow(BaseModel):
    scenario_name: str = ""
    assumptions: dict[str, str] = Field(default_factory=dict)
    outcome: str = ""
    winning_option: str = ""


class Contradiction(BaseModel):
    topic: str = ""
    position_a: str = ""
    source_a_paper_id: int = 0
    position_b: str = ""
    source_b_paper_id: int = 0
    resolution: str = ""


class EffectSize(BaseModel):
    outcome: str = ""
    comparator: str = ""
    effect: str = ""
    certainty: str = ""
    source_paper_id: int = 0


class StructuredDisagreement(BaseModel):
    topic: str = ""
    claim_a: str = ""
    source_a_paper_id: int = 0
    claim_b: str = ""
    source_b_paper_id: int = 0
    disagreement_type: Literal[
        "population",
        "intervention",
        "comparator",
        "outcome",
        "duration",
        "study_design",
        "analysis",
        "risk_of_bias",
        "publication_year",
        "statistical",
        "true_scientific",
    ] = "statistical"
    likely_explanation: str = ""
    resolution: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class ClaimLevelRobustness(BaseModel):
    claim: str = ""
    robustness: Literal[
        "robust", "probable", "uncertain", "unsupported",
    ] = "uncertain"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    supporting_sources: list[int] = Field(default_factory=list)
    contradicting_sources: list[int] = Field(default_factory=list)
    reason: str = ""


class ReasoningLedger(BaseModel):
    extracted_variables: list[ExtractedVariable] = Field(default_factory=list)
    unsupported_variables: list[str] = Field(default_factory=list)
    scenario_matrix: list[ScenarioRow] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    key_assumptions: list[str] = Field(default_factory=list)
    ledger_source: str = "llm"

    # ── Phase 2 additions ──
    effect_sizes: list[EffectSize] = Field(default_factory=list)
    disagreements: list[StructuredDisagreement] = Field(default_factory=list)
    robustness_assessment: dict[str, str] = Field(default_factory=dict)
    claim_robustness: list[ClaimLevelRobustness] = Field(default_factory=list)
