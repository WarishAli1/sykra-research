import re
from app.config import settings


MODULE_LIBRARY = {
    "direct_answer": {
        "title": "Direct Answer",
        "order": 100,
        "purpose": "Give the explicit answer to the user's question immediately.",
        "evidence_policy": "evidence_preferred",
        "requires_citations": True,
        "always": True,
    },
    "executive_summary": {
        "title": "Executive Summary",
        "order": 150,
        "purpose": "Summarize the conclusion, evidence strength, and key implications.",
        "evidence_policy": "evidence_preferred",
        "requires_citations": True,
        "always": False,
    },
    "background": {
        "title": "Background & Context",
        "order": 200,
        "purpose": "Explain necessary context and concepts needed to understand the answer.",
        "evidence_policy": "first_principles_allowed",
        "requires_citations": False,
        "always": False,
    },
    "key_concepts": {
        "title": "Key Concepts",
        "order": 250,
        "purpose": "Define important terms, mechanisms, or concepts.",
        "evidence_policy": "first_principles_allowed",
        "requires_citations": False,
        "always": False,
    },
    "methodology": {
        "title": "Methodology / Evidence Base",
        "order": 300,
        "purpose": "Explain what kind of evidence was considered and how strong it is.",
        "evidence_policy": "evidence_required",
        "requires_citations": True,
        "always": False,
    },
    "research_findings": {
        "title": "Research Findings",
        "order": 400,
        "purpose": "Synthesize the strongest evidence from retrieved sources.",
        "evidence_policy": "evidence_required",
        "requires_citations": True,
        "always": False,
    },
    "comparative_analysis": {
        "title": "Comparative Analysis",
        "order": 500,
        "purpose": "Compare options, methods, models, treatments, or approaches.",
        "evidence_policy": "evidence_preferred",
        "requires_citations": True,
        "always": False,
    },
    "independent_analysis": {
        "title": "Independent Analysis",
        "order": 600,
        "purpose": (
            "Reason beyond source summaries: evidence -> inference -> judgment. "
            "Only include when the query has genuine ambiguity, trade-offs, or "
            "open judgment calls to make."
        ),
        "evidence_policy": "first_principles_allowed",
        "requires_citations": False,
        "always": False,
    },
    "tradeoffs": {
        "title": "Trade-offs",
        "order": 650,
        "purpose": "Discuss pros, cons, and trade-offs between viable options.",
        "evidence_policy": "first_principles_allowed",
        "requires_citations": False,
        "always": False,
    },
    "risk_analysis": {
        "title": "Risk Analysis",
        "order": 700,
        "purpose": "Identify risks, failure modes, downsides, and safety concerns.",
        "evidence_policy": "first_principles_allowed",
        "requires_citations": False,
        "always": False,
    },
    "alternatives": {
        "title": "Alternatives",
        "order": 720,
        "purpose": "Present alternative approaches and when they are preferable.",
        "evidence_policy": "first_principles_allowed",
        "requires_citations": False,
        "always": False,
    },
    "implementation_plan": {
        "title": "Implementation Plan",
        "order": 800,
        "purpose": "Provide actionable steps to implement the recommendation.",
        "evidence_policy": "first_principles_allowed",
        "requires_citations": False,
        "always": False,
    },
    "timeline_roadmap": {
        "title": "Timeline & Roadmap",
        "order": 850,
        "purpose": "Provide sequencing, milestones, or rollout plan.",
        "evidence_policy": "speculative_allowed",
        "requires_citations": False,
        "always": False,
    },
    "cost_resources": {
        "title": "Cost & Resources",
        "order": 900,
        "purpose": "Discuss cost, compute, budget, team, or resource requirements.",
        "evidence_policy": "first_principles_allowed",
        "requires_citations": False,
        "always": False,
    },
    "future_outlook": {
        "title": "Future Outlook",
        "order": 950,
        "purpose": "Discuss likely future developments, scenarios, and uncertainties.",
        "evidence_policy": "speculative_allowed",
        "requires_citations": False,
        "always": False,
    },
    "limitations": {
        "title": "Limitations",
        "order": 1050,
        "purpose": "State limitations, missing evidence, scope constraints, and caveats.",
        "evidence_policy": "first_principles_allowed",
        "requires_citations": False,
        "always": False,          # ← no longer forced
    },
    "references": {
        "title": "References",
        "order": 1200,
        "purpose": "List cited sources.",
        "evidence_policy": "evidence_required",
        "requires_citations": True,
        "always": True,
    },
    "boundary_conditions": {
        "title": "Boundary Conditions & Failure Modes",
        "order": 680,
        "purpose": (
            "Explicitly detail the edge cases, contraindications, asymptotic limits, "
            "or failure modes where the dominant approach breaks down."
        ),
        "evidence_policy": "evidence_plus_analysis",
        "requires_citations": True,
        "always": False,
    },
    "derivation": {
        "title": "Derivation",
        "order": 220,
        "purpose": (
            "Derive the result from first principles, motivating each step before "
            "stating it. For every step, answer: what problem does this step solve, "
            "and why was this specific mathematical choice made over the alternatives. "
            "Define every symbol and every dimension on first use. "
            "ANTI-PATTERN TO AVOID: do not simply restate the final formula and then "
            "relabel its existing parts as 'steps'."
        ),
        "evidence_policy": "evidence_preferred",
        "requires_citations": True,
        "always": False,
    },
    "architecture": {
        "title": "Architecture",
        "order": 230,
        "purpose": (
            "Walk through the actual structure of the system component by component, "
            "in the order data flows through it. For each component: what it is, where "
            "it sits in the pipeline, what shape/dimension its input and output are, "
            "and why it is necessary."
        ),
        "evidence_policy": "evidence_preferred",
        "requires_citations": True,
        "always": False,
    },
    # ── confidence_uncertainty REMOVED ──────────────────────────────
}


REQUIRED_MODULE_IDS = [
    "direct_answer",
    # "limitations" removed – no longer forced
]




def get_disclaimer() -> str:
    """Short disclaimer that replaces coverage-gap / confidence sections."""
    return settings.RESEARCH_DISCLAIMER




def module_catalog_text() -> str:
    lines = []
    for module_id, meta in MODULE_LIBRARY.items():
        lines.append(f"- {module_id}: {meta['purpose']}")
    return "\n".join(lines)




def get_module_order(module_id: str) -> int:
    return MODULE_LIBRARY.get(module_id, {}).get("order", 9999)




def detect_domain_guardrails(
    query: str, understanding: dict | None = None
) -> list[str]:
    understanding = understanding or {}
    domain = str(understanding.get("application_domain", "") or "")
    text = f"{query} {domain}".lower()
    guardrails = []


    medical_keywords = [
        "medical", "patient", "patients", "treatment", "treatments",
        "drug", "drugs", "therapy", "therapies", "disease", "diseases",
        "clinical", "diagnosis", "symptom", "symptoms", "cancer",
        "diabetes", "health",
    ]
    legal_keywords = [
        "legal", "law", "regulation", "regulations", "compliance",
        "gdpr", "hipaa", "contract", "liability", "court", "jurisdiction",
    ]
    financial_keywords = [
        "stock", "stocks", "invest", "investing", "investment",
        "portfolio", "trading", "finance", "financial", "valuation",
        "market", "crypto", "bitcoin",
    ]
    safety_keywords = [
        "safety", "secure", "security", "risk", "hazard", "failure",
        "critical", "aviation", "nuclear", "autonomous",
    ]


    if any(k in text for k in medical_keywords):
        guardrails.append(
            "Medical domain: avoid personalized medical advice; state uncertainty "
            "clearly; recommend consultation with a qualified clinician."
        )
    if any(k in text for k in legal_keywords):
        guardrails.append(
            "Legal domain: provide general information only, not legal advice; "
            "note jurisdiction dependence."
        )
    if any(k in text for k in financial_keywords):
        guardrails.append(
            "Financial domain: avoid personalized investment advice; emphasize "
            "risk and uncertainty."
        )
    if any(k in text for k in safety_keywords):
        guardrails.append(
            "Safety-critical domain: emphasize failure modes, validation, and "
            "conservative assumptions."
        )
    return guardrails




def _is_definitional(query: str, understanding: dict | None = None) -> bool:
    q = (query or "").strip().lower()
    definitional_starts = (
        "what is ", "what are ", "what's ", "define ", "definition of ",
        "explain ", "explain what ", "what does ", "what do ",
        "how does ", "how do ", "describe ", "overview of ",
        "introduction to ",
    )
    if any(q.startswith(s) for s in definitional_starts):
        if any(
            k in q
            for k in (" derive ", " compare ", " architecture ", " step by step ", "prove ")
        ):
            return False
        return True
    understanding = understanding or {}
    objectives = [str(x).lower() for x in (understanding.get("objectives") or [])]
    return any(
        "understand" in o or "learn" in o or "explain" in o for o in objectives
    )




def _has_comparison_signal(query: str, understanding: dict | None = None) -> bool:
    q = (query or "").lower()
    explicit = any(
        w in q
        for w in (
            "compare ", "comparison ", "versus ", "vs ", "difference between ",
            "differences between ", "trade-off ", "tradeoff ", "pros and cons ",
            "advantages and disadvantages ", "better ", "faster ",
            "more efficient ", "outperform ",
        )
    )
    if explicit:
        return True
    understanding = understanding or {}
    needs = [str(x).lower() for x in (understanding.get("objectives") or [])]
    return any(
        "compare" in n or "comparison" in n or "trade" in n for n in needs
    )




def _has_visual_signal(query: str) -> bool:
    q = (query or "").lower()
    return any(
        w in q
        for w in (
            "graph ", "chart ", "plot ", "diagram ", "visualiz ",
            "visualise ", "figure ", "show me a ",
        )
    )




def _has_architecture_signal(
    query: str, understanding: dict | None = None
) -> bool:
    q = (query or "").lower()
    explicit = any(
        w in q
        for w in (
            "architecture ", "how is it structured ", "how it is structured ",
            "components of ", "structure of ", "building blocks ",
            "how it works internally ", "internal workings ", "pipeline of ",
            "layers of ",
        )
    )
    if explicit:
        return True
    understanding = understanding or {}
    objectives = [str(x).lower() for x in (understanding.get("objectives") or [])]
    return any("architecture" in o or "structure" in o for o in objectives)




def _is_technical_derivation(
    query: str, understanding: dict | None = None
) -> bool:
    q = (query or "").lower()
    signals = (
        "derive ", "derivation ", "prove ", "proof ",
        "how does ", "how do ", "mathematically ",
        "step by step ", "step-by-step ", "walk through ",
        "mechanism of ", "explain the math ",
    )
    if any(s in q for s in signals):
        return True
    understanding = understanding or {}
    methods = [
        str(x).lower()
        for x in (understanding.get("methods_techniques") or [])
    ]
    return any("equation " in m or "algorithm " in m for m in methods)




def _default_modules(
    depth: str, query: str, understanding: dict | None = None
) -> list[dict]:
    understanding = understanding or {}
    wants_architecture = _has_architecture_signal(query, understanding)


    if _is_technical_derivation(query, understanding):
        modules = [
            {"module_id": "direct_answer", "importance": 100},
            {"module_id": "derivation", "importance": 98},
            {"module_id": "key_concepts", "importance": 85},
            {"module_id": "boundary_conditions", "importance": 70},
            {"module_id": "references", "importance": 100},
        ]
        if wants_architecture:
            modules.append({"module_id": "architecture", "importance": 96})
        if _has_comparison_signal(query, understanding):
            modules.append({"module_id": "comparative_analysis", "importance": 75})
        return modules


    modules = []
    modules.append({"module_id": "direct_answer", "importance": 100})
    modules.append({"module_id": "independent_analysis", "importance": 95})
    modules.append({"module_id": "references", "importance": 100})


    if wants_architecture:
        modules.append({"module_id": "architecture", "importance": 90})


    if _is_definitional(query, understanding):
        modules.append({"module_id": "background", "importance": 85})
        modules.append({"module_id": "key_concepts", "importance": 75})


    if depth == "low":
        modules.append({"module_id": "research_findings", "importance": 70})
        return modules


    modules.append({"module_id": "executive_summary", "importance": 88})
    modules.append({"module_id": "research_findings", "importance": 90})
    modules.append({"module_id": "background", "importance": 70})


    if _has_comparison_signal(query, understanding):
        modules.append({"module_id": "comparative_analysis", "importance": 92})
        modules.append({"module_id": "tradeoffs", "importance": 82})


    if depth in ("medium", "high"):
        modules.append({"module_id": "boundary_conditions", "importance": 85})


    if depth == "high":
        modules.append({"module_id": "methodology", "importance": 72})
        modules.append({"module_id": "risk_analysis", "importance": 70})
        modules.append({"module_id": "alternatives", "importance": 65})
        modules.append({"module_id": "future_outlook", "importance": 55})
        if any(
            k in (query or "").lower()
            for k in (
                "design", "build", "plan", "strategy", "roadmap",
                "implement", "startup", "system",
            )
        ):
            modules.append({"module_id": "implementation_plan", "importance": 80})
            modules.append({"module_id": "timeline_roadmap", "importance": 60})
            modules.append({"module_id": "cost_resources", "importance": 55})


    return modules




def default_report_plan(state: dict) -> dict:
    query = state.get("query", "")
    response_mode = state.get("response_mode", "normal")
    understanding = state.get("query_understanding") or {}
    is_researched = response_mode in ("researched", "graph_research")


    ql = query.lower()
    clause_count = len([c for c in re.split(r"[.?!;]+", ql) if c.strip()])
    action_count = sum(
        1
        for w in ("explain", "derive", "compare", "analyze", "evaluate", "design")
        if w in ql
    )


    if (
        _is_definitional(query, understanding)
        and action_count <= 1
        and clause_count <= 1
    ):
        depth = "low"
        complexity = 30
    elif (
        _has_comparison_signal(query, understanding)
        or len(query.split()) > 25
        or clause_count >= 3
        or action_count >= 3
    ):
        depth = "high"
        complexity = 75
    else:
        depth = "medium"
        complexity = 55


    if _is_technical_derivation(query, understanding) and depth == "low":
        depth = "medium"
        complexity = max(complexity, 55)


    target_words = {
        "low": settings.REPORT_TARGET_WORDS_LOW,
        "medium": settings.REPORT_TARGET_WORDS_MEDIUM,
        "high": settings.REPORT_TARGET_WORDS_HIGH,
    }[depth]


    reference_policy = (
        "research" if is_researched else ("minimal" if depth == "low" else "standard")
    )
    reasoning_policy = "evidence_plus_analysis"
    if any(
        k in query.lower()
        for k in ("forecast", "future", "predict", "agi", "scenario")
    ):
        reasoning_policy = "speculative_allowed"


    raw_plan = {
        "primary_intent": "research" if is_researched else "explain",
        "secondary_intents": [],
        "information_needs": understanding.get("objectives") or [],
        "complexity_score": complexity,
        "depth": depth,
        "reference_policy": reference_policy,
        "reasoning_policy": reasoning_policy,
        "domain_guardrails": detect_domain_guardrails(query, understanding),
        "modules": _default_modules(depth, query, understanding),
        "target_words": target_words,
    }
    return normalize_report_plan(raw_plan, state)




def normalize_report_plan(raw_plan: dict, state: dict) -> dict:
    query = state.get("query", "")
    understanding = state.get("query_understanding") or {}
    response_mode = state.get("response_mode", "normal")
    depth = raw_plan.get("depth", "low")


    if depth not in ("low", "medium", "high"):
        depth = "low"


    if depth == "low":
        threshold = settings.REPORT_MODULE_THRESHOLD_LOW
        max_modules = settings.REPORT_MAX_MODULES_LOW
        default_target_words = settings.REPORT_TARGET_WORDS_LOW
    elif depth == "medium":
        threshold = settings.REPORT_MODULE_THRESHOLD_MEDIUM
        max_modules = settings.REPORT_MAX_MODULES_MEDIUM
        default_target_words = settings.REPORT_TARGET_WORDS_MEDIUM
    else:
        threshold = settings.REPORT_MODULE_THRESHOLD_HIGH
        max_modules = settings.REPORT_MAX_MODULES_HIGH
        default_target_words = settings.REPORT_TARGET_WORDS_HIGH


    target_words = int(raw_plan.get("target_words") or default_target_words)


    epistemic_mode = "research_synthesis"
    if _is_technical_derivation(query, understanding):
        epistemic_mode = "textbook_derivation"
    elif _is_definitional(query, understanding):
        epistemic_mode = "conceptual_explanation"


    selected = []
    seen = set()
    raw_modules = raw_plan.get("modules") or []


    for m in raw_modules:
        if hasattr(m, "model_dump"):
            m = m.model_dump()
        module_id = str(m.get("module_id", "")).strip()
        if module_id not in MODULE_LIBRARY:
            continue
        importance = int(m.get("importance", 0) or 0)
        meta = MODULE_LIBRARY[module_id]
        if meta.get("always"):
            importance = max(importance, 95)
        if importance < threshold and module_id not in REQUIRED_MODULE_IDS:
            continue
        if module_id in seen:
            continue
        selected.append({"module_id": module_id, "importance": importance})
        seen.add(module_id)


    BANNED_IN_DERIVATION = {
        "research_findings", "independent_analysis", "executive_summary",
        "future_outlook", "methodology", "implementation_plan",
        "timeline_roadmap", "cost_resources", "alternatives",
        "risk_analysis", "tradeoffs", "limitations",
    }
    if epistemic_mode == "textbook_derivation":
        selected = [m for m in selected if m["module_id"] not in BANNED_IN_DERIVATION]
        seen = {m["module_id"] for m in selected}


    dynamic_required = list(REQUIRED_MODULE_IDS)
    if epistemic_mode == "textbook_derivation":
        for must_have in ("derivation", "boundary_conditions"):
            if must_have not in dynamic_required:
                dynamic_required.append(must_have)


    if (
        _has_architecture_signal(query, understanding)
        and "architecture" not in dynamic_required
    ):
        dynamic_required.append("architecture")


    for module_id in dynamic_required:
        if module_id not in seen:
            selected.append({"module_id": module_id, "importance": 100})
            seen.add(module_id)


    if "references" not in seen:
        selected.append({"module_id": "references", "importance": 100})
        seen.add("references")


    selected.sort(
        key=lambda x: (-x["importance"], MODULE_LIBRARY[x["module_id"]]["order"])
    )


    required_selected = [
        m
        for m in selected
        if m["module_id"] in dynamic_required or m["module_id"] == "references"
    ]
    optional_selected = [m for m in selected if m not in required_selected]
    remaining_slots = max(0, max_modules - len(required_selected))
    selected = required_selected + optional_selected[:remaining_slots]


    generative_modules = [
        m
        for m in selected
        if m["module_id"] not in ("references",)
    ]
    total_importance = sum(m["importance"] for m in generative_modules) or 1


    normalized_modules = []
    for m in selected:
        module_id = m["module_id"]
        meta = MODULE_LIBRARY[module_id]
        if module_id == "references":
            module_target = 0
        else:
            module_target = max(
                80,
                int(target_words * 0.92 * m["importance"] / total_importance),
            )
        normalized_modules.append(
            {
                "module_id": module_id,
                "title": meta["title"],
                "importance": m["importance"],
                "order": meta["order"],
                "purpose": meta["purpose"],
                "evidence_policy": meta["evidence_policy"],
                "requires_citations": meta["requires_citations"],
                "target_words": module_target,
            }
        )


    normalized_modules.sort(key=lambda x: x["order"])


    information_needs = []
    for need in raw_plan.get("information_needs") or []:
        need = str(need).strip().lower()
        if need and need not in information_needs:
            information_needs.append(need)


    if (
        _has_comparison_signal(query, understanding)
        and "comparison" not in information_needs
    ):
        information_needs.append("comparison")
    if _is_definitional(query, understanding) and "background" not in information_needs:
        information_needs.append("background")
    if _has_visual_signal(query) and "visualization" not in information_needs:
        information_needs.append("visualization")


    guardrails = raw_plan.get("domain_guardrails") or detect_domain_guardrails(
        query, understanding
    )
    latency_notice = raw_plan.get("latency_notice")
    if not latency_notice:
        if depth == "high":
            latency_notice = (
                "Deep research mode can take around 25–35 seconds. "
                "Generating a structured report."
            )
        elif depth == "medium" and response_mode in ("researched", "graph_research"):
            latency_notice = "This research answer may take around 15–25 seconds."
        else:
            latency_notice = None


    return {
        "primary_intent": raw_plan.get("primary_intent", "research"),
        "secondary_intents": raw_plan.get("secondary_intents", []),
        "information_needs": information_needs,
        "complexity_score": int(raw_plan.get("complexity_score", 50) or 50),
        "depth": depth,
        "target_words": target_words,
        "reference_policy": raw_plan.get("reference_policy", "standard"),
        "reasoning_policy": raw_plan.get(
            "reasoning_policy", "evidence_plus_analysis"
        ),
        "domain_guardrails": guardrails,
        "epistemic_mode": epistemic_mode,
        "modules": normalized_modules,
        "latency_notice": latency_notice,
    }