import json
import re as _re

from langchain_core.messages import SystemMessage, HumanMessage

from app.config import settings
from app.services.llm_client import get_llm, is_llm_rate_limited
from app.agents.state import AgentState
from app.agents.schemas import AnswerSpec


_ANSWER_SPEC_PROMPT = """You are a research director and answer planner.

Your job is NOT to answer the question.
Your job is to create a precise specification for what a correct, premium answer must contain.

USER QUESTION:
{query}

CONVERSATION CONTEXT:
{conversation_history}

TASK:
Analyze the question and produce an AnswerSpec JSON object.

EVIDENCE CONTRACT:
If the query specifies a date constraint, include it in evidence_contract constraints.
Examples:
- "since 2020" => publication_year gte 2020
- "before 2018" => publication_year lte 2018
- "between 2018 and 2022" => publication_year gte 2018 and publication_year lte 2022

If the query specifies study types, include them with field="study_type", strength="hard".

Rules:
Identify exact question types.
Separate explicit requirements from optional background.
Extract canonical entities, methods, systems, theories, people, datasets, or papers.
For canonical/historical/original concepts, propose likely primary source if known.
If the question asks for original architecture, theory, algorithm, equation, or derivation, set primary_source_required=true.
If the question asks for derivation, proof, formula, mechanism math, or equation explanation, set equation_verification_required=true.
List expected equations in canonical form if known.
List required answer components.
List non-goals.
Generate exact_search_queries for retrieval.
Generate retrieval_focus queries.
If numbers are required, set quantitative_required=true.
If trade-offs/forecasting are required, set scenario_analysis_required=true.

Return only JSON matching AnswerSpec.
"""


FOUNDATIONAL_PAPERS = {
    "transformer": {
        "title": "Attention is All You Need",
        "keywords": [
            "transformer",
            "transformers",
            "attention mechanism",
            "self-attention",
            "scaled dot-product attention",
            "llm",
            "large language model",
            "large language models",
        ],
    },
    "cnn": {
        "title": "ImageNet Classification with Deep Convolutional Neural Networks",
        "keywords": [
            "cnn",
            "cnns",
            "convolutional neural network",
            "convolutional neural networks",
            "convnet",
            "alexnet",
            "image classification",
        ],
    },
    "gan": {
        "title": "Generative Adversarial Networks",
        "keywords": [
            "gan",
            "gans",
            "generative adversarial network",
            "generative adversarial networks",
        ],
    },
    "resnet": {
        "title": "Deep Residual Learning for Image Recognition",
        "keywords": [
            "resnet",
            "residual network",
            "residual learning",
        ],
    },
    "bert": {
        "title": "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
        "keywords": [
            "bert",
            "bidirectional transformer",
        ],
    },
    "diffusion": {
        "title": "Denoising Diffusion Probabilistic Models",
        "keywords": [
            "diffusion model",
            "diffusion models",
            "ddpm",
            "denoising diffusion",
        ],
    },
    "word2vec": {
        "title": "Efficient Estimation of Word Representations in Vector Space",
        "keywords": [
            "word2vec",
            "word embeddings",
            "word representations",
        ],
    },
    "lstm": {
        "title": "Long Short-Term Memory",
        "keywords": [
            "lstm",
            "long short-term memory",
            "recurrent neural network",
        ],
    },
}


def detect_foundational_papers(query: str) -> list[dict]:
    q = (query or "").lower()
    found = []

    for topic, spec in FOUNDATIONAL_PAPERS.items():
        if any(keyword in q for keyword in spec["keywords"]):
            found.append(
                {
                    "topic": topic,
                    "title": spec["title"],
                }
            )

    return found


def _parse_date_constraints(query: str) -> dict:
    """
    Parse date constraints from query.

    Supports:
    - since/from/after 2020
    - 2020 or later
    - before/until/up to 2020
    - 2020 or earlier
    - between 2018 and 2022
    - from 2018 to 2022
    - 2018-2022
    """
    q = (query or "").lower()

    min_year = None
    max_year = None

    m = _re.search(r"between\s+(20\d{2})\s+and\s+(20\d{2})", q)
    if m:
        return {
            "min_year": int(m.group(1)),
            "max_year": int(m.group(2)),
        }

    m = _re.search(r"from\s+(20\d{2})\s+(?:to|until)\s+(20\d{2})", q)
    if m:
        return {
            "min_year": int(m.group(1)),
            "max_year": int(m.group(2)),
        }

    m = _re.search(r"\b(20\d{2})\s*[-–]\s*(20\d{2})\b", q)
    if m:
        return {
            "min_year": int(m.group(1)),
            "max_year": int(m.group(2)),
        }

    for pattern in [
        r"(?:since|from|after)\s+(20\d{2})",
        r"(20\d{2})\s+or\s+later",
        r"(?:published\s+)?(?:in|after|since|from)\s+(20\d{2})",
    ]:
        m = _re.search(pattern, q)
        if m:
            min_year = int(m.group(1))
            break

    for pattern in [
        r"(?:before|until|up\s+to|prior\s+to)\s+(20\d{2})",
        r"(20\d{2})\s+or\s+earlier",
    ]:
        m = _re.search(pattern, q)
        if m:
            max_year = int(m.group(1))
            break

    return {
        "min_year": min_year,
        "max_year": max_year,
    }


def _parse_study_types(query: str) -> list[str]:
    q = (query or "").lower()
    types = []

    if any(
        phrase in q
        for phrase in (
            "meta-analysis",
            "meta-analyses",
            "meta analysis",
            "systematic review",
            "systematic reviews",
        )
    ):
        types.append("meta-analysis")

    if any(
        phrase in q
        for phrase in (
            "rct",
            "rcts",
            "randomized controlled trial",
            "randomized controlled trials",
            "randomised controlled trial",
            "randomised controlled trials",
            "randomized trial",
            "randomised trial",
        )
    ):
        types.append("RCT")

    if "cohort" in q:
        types.append("cohort")

    if "case-control" in q or "case control" in q:
        types.append("case-control")

    if "guideline" in q or "consensus statement" in q:
        types.append("guideline")

    return types


def _detect_domain(query: str) -> str:
    q = (query or "").lower()

    medical_kw = [
        "patient", "clinical", "treatment", "drug", "therapy",
        "disease", "trial", "rct", "meta-analysis", "health",
        "medical", "dose", "mortality", "morbidity",
    ]

    econ_kw = [
        "gdp", "inflation", "market", "trade", "fiscal",
        "monetary", "labor", "employment",
    ]

    climate_kw = [
        "climate", "emission", "carbon", "temperature",
        "warming", "renewable", "energy transition",
    ]

    tech_kw = [
        "algorithm", "model", "neural", "transformer",
        "benchmark", "latency", "throughput", "gpu", "training",
    ]

    legal_kw = [
        "regulation", "compliance", "law", "court",
        "jurisdiction", "statute",
    ]

    if sum(1 for k in medical_kw if k in q) >= 2:
        return "medicine"

    if sum(1 for k in econ_kw if k in q) >= 2:
        return "economics"

    if sum(1 for k in climate_kw if k in q) >= 2:
        return "climate"

    if sum(1 for k in tech_kw if k in q) >= 2:
        return "technology"

    if sum(1 for k in legal_kw if k in q) >= 2:
        return "legal"

    return "general"


def _build_evidence_contract(query: str) -> dict:
    constraints = []

    dates = _parse_date_constraints(query)

    if dates.get("min_year"):
        constraints.append(
            {
                "field": "publication_year",
                "operator": "gte",
                "value": dates["min_year"],
                "strength": "hard",
                "description": f"Publication year >= {dates['min_year']}",
            }
        )

    if dates.get("max_year"):
        constraints.append(
            {
                "field": "publication_year",
                "operator": "lte",
                "value": dates["max_year"],
                "strength": "hard",
                "description": f"Publication year <= {dates['max_year']}",
            }
        )

    for study_type in _parse_study_types(query):
        constraints.append(
            {
                "field": "study_type",
                "operator": "contains",
                "value": study_type,
                "strength": "hard",
                "description": f"Study type includes {study_type}",
            }
        )

    return {
        "constraints": constraints,
        "analytical_requirements": [],
        "evidence_hierarchy": [],
        "required_output_sections": [],
        "minimum_evidence_count": 3,
        "consensus_required": False,
        "primary_source_required": False,
    }


def _default_answer_spec(query: str, understanding: dict | None = None) -> AnswerSpec:
    understanding = understanding or {}
    q = (query or "").lower()

    question_types = []

    if any(
        w in q
        for w in (
            "derive",
            "derivation",
            "prove",
            "proof",
            "mathematically",
            "step by step",
            "step-by-step",
        )
    ):
        question_types.append("mathematical_derivation")

    if any(
        w in q
        for w in (
            "explain",
            "describe",
            "what is",
            "what are",
            "define",
            "how does",
            "how do",
        )
    ):
        if any(
            w in q
            for w in (
                "architecture",
                "mechanism",
                "algorithm",
                "system",
                "model",
            )
        ):
            question_types.append("technical_explanation")
        else:
            question_types.append("conceptual")

    if any(
        w in q
        for w in (
            "compare",
            "comparison",
            "versus",
            " vs",
            "difference between",
        )
    ):
        question_types.append("comparison")

    if any(
        w in q
        for w in (
            "implement",
            "implementation",
            "how to build",
            "pipeline",
        )
    ):
        question_types.append("implementation")

    if not question_types:
        question_types.append("conceptual")

    primary_source_required = any(
        w in q
        for w in (
            "original",
            "origin",
            "first introduced",
            "seminal",
            "canonical",
            "derive",
            "derivation",
            "prove",
            "proof",
            "architecture of",
        )
    )

    equation_verification_required = any(
        w in q
        for w in (
            "derive",
            "derivation",
            "equation",
            "formula",
            "proof",
            "mathematically",
        )
    ) or "mathematical_derivation" in question_types

    quantitative_required = any(
        w in q
        for w in (
            "quantify",
            "how much",
            "how many",
            "cost",
            "price",
            "estimate",
            "calculate",
            "investment",
            "budget",
            "capacity",
            "demand",
            "emissions",
            "percentage",
            "percent",
        )
    )

    scenario_analysis_required = any(
        w in q
        for w in (
            "scenario",
            "sensitivity",
            "resilient",
            "robust",
            "trade-off",
            "tradeoff",
            "what if",
            "forecast",
            "projection",
            "uncertainty",
            "compare",
        )
    )

    difficulty = 3

    if any(
        w in q
        for w in (
            "consensus",
            "disagree",
            "disagreement",
            "compare rct",
            "compare meta",
        )
    ):
        difficulty = 5
    elif any(
        w in q
        for w in (
            "evidence",
            "systematic",
            "meta-analysis",
            "rct",
        )
    ):
        difficulty = 4
    elif any(w in q for w in ("compare", "versus", "trade-off")):
        difficulty = 3
    elif any(w in q for w in ("explain", "what is", "define")):
        difficulty = 2

    return AnswerSpec(
        question_types=question_types,
        domain=understanding.get("application_domain") or "",
        answer_intent=query,
        requirements=[],
        canonical_entities=[],
        foundational_papers=[],
        primary_source_required=primary_source_required,
        equation_verification_required=equation_verification_required,
        expected_equations=[],
        expected_components=[],
        non_goals=[],
        answer_outline=[],
        retrieval_focus=[],
        exact_search_queries=[],
        quantitative_required=quantitative_required,
        scenario_analysis_required=scenario_analysis_required,
        required_quantitative_variables=[],
        scenario_dimensions=[],
        required_source_tiers=[],
        epistemic_abstention_triggers=[],
        evidence_contract=_build_evidence_contract(query),
        difficulty_level=difficulty,
        domain_evidence_policy=_detect_domain(query),
    )


def answer_spec_node(state: AgentState) -> AgentState:
    query = state["query"]
    history = state.get("conversation_history", []) or []
    understanding = state.get("query_understanding") or {}
    mode = state.get("response_mode", "normal")

    is_normal = mode == "normal"

    allow_llm = (
        not is_normal
        and state.get("evidence_mode") != "uploaded"
        and not is_llm_rate_limited()
        and getattr(settings, "LLM_ANSWER_SPEC_ENABLED", True)
    )

    spec = None

    if allow_llm:
        try:
            llm = get_llm(temperature=0, task="structured")

            raw = llm.invoke_json_mode(
                [
                    SystemMessage(
                        content=(
                            "You are a research director and answer planner. "
                            "Return ONLY a valid JSON object matching AnswerSpec. "
                            "No markdown fences. No explanations."
                        )
                    ),
                    HumanMessage(
                        content=_ANSWER_SPEC_PROMPT.format(
                            query=query,
                            conversation_history=(
                                json.dumps(history[-6:], default=str)
                                if history
                                else "none"
                            ),
                        )
                    ),
                ],
                schema=AnswerSpec,
                config={"timeout": 10},
            )

            if isinstance(raw, dict):
                spec = AnswerSpec.model_validate(raw)
            else:
                spec = raw

        except Exception as e:
            print(
                f"[answer_spec] LLM planning failed, using fallback: "
                f"{type(e).__name__}: {e}"
            )

    if spec is None:
        spec = _default_answer_spec(query, understanding)

    data = spec.model_dump()

    foundational = detect_foundational_papers(query)

    if foundational:
        data["foundational_papers"] = foundational

        retrieval_focus = data.get("retrieval_focus") or []

        for fp in foundational:
            title = fp.get("title", "")
            if title:
                retrieval_focus.append(f'"{title}"')

        data["retrieval_focus"] = retrieval_focus

    return {
        "answer_spec": data,
        "evidence_contract": data.get("evidence_contract"),
        "source_plan": {
            "canonical_entities": data.get("canonical_entities", []),
        },
    }