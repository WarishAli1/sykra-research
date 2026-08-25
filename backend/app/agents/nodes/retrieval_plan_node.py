import re

from langchain_core.messages import SystemMessage, HumanMessage

from app.agents.state import AgentState
from app.agents.schemas import RetrievalIntent, RetrievalPlan
from app.services.llm_client import get_llm, is_llm_rate_limited


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


_GENERIC_PROBE_SUFFIXES = [
    "environmental impact",
    "advantages disadvantages",
    "health effects hazards",
    "pollution emissions",
    "quantitative figures data",
]


def _decompose_uploaded_query(query: str) -> list[str]:
    """
    Deterministic (no-LLM) sub-topic decomposition for uploaded-document
    retrieval. Splits the query into coordinate items (X and Y, X vs Y,
    X, Y, Z) and pairs each with a few fixed generic-coverage probes, so
    a single broad question against a multi-chapter document triggers
    more than one retrieval pass. This does not call external search APIs,
    matching this node's contract.
    """
    q = str(query or "").strip()
    if not q:
        return []

    first_sentence = re.split(r"[.?!]", q)[0].strip()

    split_parts = re.split(
        r"\b(?:discuss|include|focus|covering|compare|comparison|explain|describe)\b",
        first_sentence,
        maxsplit=1,
        flags=re.IGNORECASE,
    )
    core = (split_parts[-1] if split_parts else first_sentence).strip(" .,")

    items = re.split(
        r"\s*(?:,| and | vs\.? | versus | & )\s*",
        core,
        flags=re.IGNORECASE,
    )

    cleaned_items = []
    for item in items:
        item = item.strip(" .,")
        item = re.sub(
            r"^(the|of|explain|compare|comparison of)\s+",
            "",
            item,
            flags=re.IGNORECASE,
        )
        item = item.strip(" .,")
        if 3 <= len(item) <= 90:
            cleaned_items.append(item)

    decomposed = [q]

    for item in cleaned_items[:4]:
        for suffix in _GENERIC_PROBE_SUFFIXES:
            decomposed.append(f"{item} {suffix}")

    if not cleaned_items:
        for suffix in _GENERIC_PROBE_SUFFIXES:
            decomposed.append(f"{q} {suffix}")

    return _dedupe(decomposed)


def _is_complex_uploaded_query(query: str) -> bool:
    """
    Cheap heuristic to decide whether an uploaded-mode question is broad
    enough to deserve one LLM decomposition call.
    """
    q = (query or "").lower()

    if len((query or "").split()) >= 12:
        return True

    broad_markers = (
        "compare",
        "across",
        "all ",
        "discuss",
        "environmental impact",
        "advantages and disadvantages",
        "renewable and non-renewable",
        "impact of",
        "effects of",
    )
    return any(marker in q for marker in broad_markers)


def _llm_decompose_uploaded(query: str) -> list[str]:
    """
    Optional single LLM call for complex uploaded questions.
    This is deliberately defensive: any failure returns [] and the
    deterministic decomposition is still used.
    """
    try:
        if is_llm_rate_limited():
            return []

        llm = get_llm(temperature=0, task="fast")

        raw = llm.invoke_json_mode(
            [
                SystemMessage(
                    content=(
                        "You decompose one broad question about an uploaded document "
                        "into precise retrieval sub-queries. Return ONLY a JSON object. "
                        "No markdown. No explanations."
                    )
                ),
                HumanMessage(
                    content=(
                        f"Question: {query}\n\n"
                        'Return JSON: {"sub_queries": ["...", "..."]} with 4 to 6 short '
                        "sub-queries that together cover every facet of the question. "
                        "Use varied vocabulary, such as impacts, health effects, pollution, "
                        "emissions, hazards, advantages, disadvantages, benefits, limitations, "
                        "and quantitative figures. Do not repeat the original question verbatim "
                        "more than once."
                    )
                ),
            ],
            config={"timeout": 5},
        )

        values = []
        if isinstance(raw, dict):
            values = raw.get("sub_queries") or raw.get("queries") or []

        if isinstance(values, str):
            values = [part.strip() for part in re.split(r"[;,\n]", values)]

        items = []
        for value in values or []:
            value = str(value or "").strip()
            if 4 <= len(value) <= 140:
                items.append(value)

        return items[:6]

    except Exception as e:
        print(
            f"[retrieval_plan] uploaded LLM decomposition failed: "
            f"{type(e).__name__}: {e}"
        )
        return []


def _intent_dedup_key(query: str) -> str:
    """
    Normalize an intent query for deduplication so '"IPCC AR6"' (canonical
    source intent) and 'IPCC AR6' (exact search intent) are recognized as
    the same retrieval need instead of executing the same search twice.
    """
    q = (query or "").strip().lower()
    q = q.replace('"', "").replace("'", "")
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

    This node must not call external search APIs.
    In uploaded mode, it now performs multi-query decomposition so the
    uploaded retriever can issue several searches instead of one raw query.
    """
    mode = state.get("response_mode", "normal")
    answer_spec = state.get("answer_spec") or {}
    understanding = state.get("query_understanding") or {}

    print(
        f"[retrieval_plan] entered "
        f"evidence_mode={state.get('evidence_mode')!r} "
        f"response_mode={mode!r} "
        f"query={str(state.get('query', ''))[:100]!r}"
    )

    question_types = set(answer_spec.get("question_types") or [])
    official_capabilities = _official_capabilities(question_types)

    domain_policy = str(
        answer_spec.get("domain_evidence_policy") or "general"
    ).lower()

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

        capabilities = _dedupe(capabilities) or ["secondary_research"]

        intents.append(
            RetrievalIntent(
                query=intent_query,
                purpose=purpose,
                priority=max(1, min(int(priority), 3)),
                source_capabilities=capabilities,
            ).model_dump()
        )

    is_uploaded = state.get("evidence_mode") == "uploaded"

    if is_uploaded:
        main_topic = str(
            understanding.get("main_topic") or state.get("query", "")
        ).strip()

        deterministic = _decompose_uploaded_query(main_topic)

        decomposed = deterministic
        if _is_complex_uploaded_query(main_topic):
            llm_queries = _llm_decompose_uploaded(main_topic)
            if llm_queries:
                decomposed = _dedupe(
                    [main_topic] + llm_queries + deterministic
                )

        print(
            f"[retrieval_plan] uploaded decomposition "
            f"main_topic={main_topic!r} "
            f"decomposed_count={len(decomposed)} "
            f"sample={decomposed[:6]}"
        )

        for i, sub_query in enumerate(decomposed):
            add_intent(
                sub_query,
                "requirement",
                3 if i == 0 else 2,
                ["secondary_research"],
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
        main_topic = str(
            understanding.get("main_topic") or state.get("query", "")
        ).strip()

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

    if is_uploaded:
        max_search_intents = 6
    else:
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

    print(
        f"[retrieval_plan] final intents={len(intents)} "
        f"queries={[i['query'][:80] for i in intents]}"
    )

    return {
        "retrieval_plan": plan.model_dump(),
    }