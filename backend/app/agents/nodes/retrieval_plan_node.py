import re
from app.agents.state import AgentState
from app.agents.schemas import RetrievalIntent, RetrievalPlan


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    out = []

    for item in items:
        item = str(item or "").strip()

        if not item:
            continue

        key = item.lower()

        if key in seen:
            continue

        seen.add(key)
        out.append(item)

    return out

def _intent_dedup_key(query: str) -> str:
    """
    Normalize an intent query for deduplication so '"IPCC AR6"' (canonical
    source intent) and 'IPCC AR6' (exact search intent) are recognized as
    the same retrieval need instead of executing the same search twice.
    """
    q = (query or "").strip().lower()
    q = q.replace('"', " ").replace("'", " ")
    return re.sub(r"\s+", " ", q).strip()


def _official_capabilities(question_types: set[str]) -> list[str]:
    """
    Derive official-authority capabilities from structured AnswerSpec question types.

    This does not use domain keyword dictionaries.
    It uses the semantic classification already produced by AnswerSpec.
    """
    capabilities = []

    if "clinical" in question_types:
        capabilities.append("official_authority_clinical")

    if "legal" in question_types:
        capabilities.append("official_authority_legal")

    if "financial" in question_types:
        capabilities.append("official_authority_financial")

    if capabilities:
        capabilities.append("official_authority")

    return _dedupe(capabilities)


def _purpose_for_kind(kind: str) -> str:
    if kind in ("derivation", "equation"):
        return "equation"

    if kind == "comparison":
        return "comparison"

    if kind == "historical_origin":
        return "canonical_source"

    return "requirement"


def _capabilities_for_requirement(
    requirement: dict,
    answer_spec: dict,
    official_capabilities: list[str],
) -> list[str]:
    kind = str(requirement.get("kind") or "background")

    capabilities: list[str] = []

    if kind in ("derivation", "equation"):
        capabilities.extend(
            [
                "primary_research",
                "secondary_research",
            ]
        )

    elif kind in (
        "historical_origin",
        "architecture",
        "mechanism",
    ):
        capabilities.extend(
            [
                "primary_research",
                "secondary_research",
            ]
        )

    elif kind == "comparison":
        capabilities.append("secondary_research")

    elif kind == "implementation":
        capabilities.extend(
            [
                "technical_documentation",
                "secondary_research",
            ]
        )

    else:
        capabilities.append("secondary_research")

    if answer_spec.get("primary_source_required"):
        if kind in (
            "derivation",
            "equation",
            "historical_origin",
            "architecture",
            "mechanism",
        ):
            if "primary_research" not in capabilities:
                capabilities.insert(0, "primary_research")

    if official_capabilities:
        capabilities.extend(official_capabilities)

    return _dedupe(capabilities) or ["secondary_research"]


def retrieval_plan_node(state: AgentState) -> AgentState:
    """
    Deterministically transform AnswerSpec + query understanding into a RetrievalPlan.

    This node must not call the LLM.
    This node must not call external search APIs.
    """
    mode = state.get("response_mode", "normal")

    answer_spec = state.get("answer_spec") or {}
    understanding = state.get("query_understanding") or {}

    question_types = set(answer_spec.get("question_types") or [])

    official_capabilities = _official_capabilities(question_types)

    domain_policy = str(answer_spec.get("domain_evidence_policy") or "general").lower()
    if domain_policy in ("economics", "financial", "legal", "climate"):
        if "official_authority" not in official_capabilities:
            official_capabilities.append("official_authority")
        if domain_policy in ("economics", "financial"):
            if "official_authority_financial" not in official_capabilities:
                official_capabilities.append("official_authority_financial")


    intents: list[dict] = []
    seen_queries: set[str] = set()

    def add_intent(
        intent_query: str,
        purpose: str,
        priority: int,
        capabilities: list[str],
    ) -> None:
        intent_query = str(intent_query or "").strip()

        if not intent_query:
            return

        key = _intent_dedup_key(intent_query)
        if not key or key in seen_queries:
            return
        seen_queries.add(key)

        if key in seen_queries:
            return

        seen_queries.add(key)

        capabilities = _dedupe(capabilities) or ["secondary_research"]

        intents.append(
            RetrievalIntent(
                query=intent_query,
                purpose=purpose,
                priority=max(1, min(int(priority), 3)),
                source_capabilities=capabilities,
            ).model_dump()
        )

    for entity in answer_spec.get("canonical_entities", [])[:2]:
        title = str(entity.get("expected_primary_source") or "").strip()

        if title:
            add_intent(
                f'"{title}"',
                "canonical_source",
                3,
                ["primary_research"],
            )

    for exact_query in answer_spec.get("exact_search_queries", [])[:3]:
        exact_query = str(exact_query).strip()

        if not exact_query:
            continue

        if answer_spec.get("primary_source_required"):
            add_intent(
                exact_query,
                "canonical_source",
                3,
                ["primary_research"] + official_capabilities,
            )
        else:
            add_intent(
                exact_query,
                "requirement",
                2,
                ["secondary_research"] + official_capabilities,
            )


    requirements = sorted(
        answer_spec.get("requirements") or [],
        key=lambda r: int(r.get("weight", 1) or 1),
        reverse=True,
    )

    for requirement in requirements[:4]:
        text = str(requirement.get("text") or "").strip()

        if not text:
            continue

        kind = str(requirement.get("kind") or "background")

        add_intent(
            text,
            _purpose_for_kind(kind),
            int(requirement.get("weight", 1) or 1),
            _capabilities_for_requirement(
                requirement,
                answer_spec,
                official_capabilities,
            ),
        )

    for focus_query in answer_spec.get("retrieval_focus", [])[:2]:
        focus_query = str(focus_query).strip()

        if not focus_query:
            continue

        add_intent(
            focus_query,
            "requirement",
            2,
            ["secondary_research"] + official_capabilities,
        )

    if not intents:
        main_topic = str(understanding.get("main_topic") or state.get("query", "")).strip()

        add_intent(
            main_topic,
            "requirement",
            1,
            ["secondary_research"],
        )

    intents.sort(
        key=lambda x: (
            int(x.get("priority", 1) or 1),
            x.get("purpose") == "canonical_source",
        ),
        reverse=True,
    )

    max_search_intents = 3 if mode == "normal" else 4
    intents = intents[:max_search_intents]

    all_capabilities = set()

    for intent in intents:
        all_capabilities.update(
            intent.get("source_capabilities", [])
        )

    web_only_capabilities = {
        "official_authority",
        "official_authority_clinical",
        "official_authority_legal",
        "official_authority_financial",
        "technical_documentation",
        "current_information",
        "standards",
        "statistics",
    }

    use_foundational_search = (
        mode != "normal"
        and (
            answer_spec.get("primary_source_required")
            or "primary_research" in all_capabilities
        )
    )

    use_citation_backtracking = (
        mode != "normal"
        and bool(all_capabilities)
        and (
            "primary_research" in all_capabilities
            or "secondary_research" in all_capabilities
        )
        and not all(
            capability in web_only_capabilities
            for capability in all_capabilities
        )
    )

    plan = RetrievalPlan(
        intents=[RetrievalIntent(**intent) for intent in intents],
        primary_source_required=bool(answer_spec.get("primary_source_required")),
        freshness_required=bool(answer_spec.get("freshness_required", False)),
        use_foundational_search=use_foundational_search,
        use_citation_backtracking=use_citation_backtracking,
        max_search_intents=max_search_intents,
    )

    return {
        "retrieval_plan": plan.model_dump(),
    }