from langchain_core.messages import SystemMessage, HumanMessage
from app.agents.state import AgentState
from app.agents.schemas import ReportPlanLLM
from app.agents.report_modules import (
    module_catalog_text,
    normalize_report_plan,
    default_report_plan,
)
from app.services.llm_client import get_llm
from app.config import settings

_REPORT_PLAN_SYSTEM = """
You are a research report planner.
Your job is NOT to answer the question.
Your job is to decide what kind of report should be generated, sized to the ACTUAL
complexity of the query — not to the response mode.
Choose modules from the module library only.
Always include direct_answer, limitations, references.
Add a module only if it would materially change or deepen the answer.
Never add a module just to fill out the report.

If the query asks to derive, prove, or mathematically explain a mechanism (not just
"what is X"), select the derivation module instead of methodology/research_findings,
and do NOT select independent_analysis or comparative_analysis unless the query
explicitly asks to compare things. A derivation question needs ONE authoritative
primary source, not a literature survey.
"""

_REPORT_PLAN_PROMPT = """
USER QUERY:
{query}

RESPONSE MODE:
{response_mode}

EVIDENCE MODE:
{evidence_mode}

QUERY UNDERSTANDING:
{understanding}

MODULE LIBRARY:
{catalog}

DEPTH RULES (apply regardless of response mode):
- depth=low: the query asks for a single fact, definition, or "what is X" — one clear
  answer exists, no real trade-offs to weigh. 3-4 modules max.
- depth=medium: the query has 2-3 distinct facets, asks "how/why" with some nuance,
  or involves a light comparison. 5-6 modules.
- depth=high: the query is genuinely multi-part, explicitly comparative, asks for
  trade-offs/risk/forecast, has constraints that require weighing evidence against
  each other, or explicitly asks for depth ("comprehensive", "in detail", "analyze").

Response mode controls how MANY sources get retrieved and how well-evidenced each
module is — it does NOT mean every researched-mode query deserves a high-depth report.
A simple definitional query in researched mode should still come back as depth=low or
medium, just backed by stronger citations than normal mode would use.

Return a ReportPlanLLM object.
"""


def _adaptive_target_paper_k(plan: dict, state: AgentState) -> int:
    """
    Normal mode  → 4–7 papers
    Researched   → 8–15 papers
    Both scale with depth, complexity, and information-needs.
    """
    response_mode = state.get("response_mode", "normal")
    depth = plan.get("depth", "low")
    is_normal = response_mode == "normal"


    if is_normal:
        base = {"low": 4, "medium": 5, "high": 7}.get(depth, 5)
        lo, hi = settings.TOP_K_PAPERS_NORMAL_MIN, settings.TOP_K_PAPERS_NORMAL_MAX
    else:
        base = {"low": 8, "medium": 11, "high": 15}.get(depth, 11)
        lo, hi = settings.TOP_K_PAPERS_RESEARCH_MIN, settings.TOP_K_PAPERS_RESEARCH_MAX


    target = base
    information_needs = [
        str(x).lower() for x in plan.get("information_needs", [])
    ]
    if any(
        x in information_needs
        for x in ("comparison", "compare", "tradeoffs", "trade-off")
    ):
        target += 1
    if any(
        x in information_needs
        for x in ("forecast", "future", "prediction", "outlook")
    ):
        target += 1


    complexity = int(plan.get("complexity_score", 50) or 50)
    if complexity >= 75:
        target += 1
    if len(information_needs) >= 6:
        target += 1


    if state.get("evidence_mode") in ("uploaded", "blended"):
        target = max(target, settings.TOP_K_PAPERS_MEDIUM)


    target = max(lo, min(hi, target))
    return int(target)


def report_plan_node(state: AgentState) -> AgentState:
    response_mode = state.get("response_mode", "normal")
    evidence_mode = state.get("evidence_mode", "literature")

    if response_mode == "normal":
        raw_plan = default_report_plan(state)
        plan = normalize_report_plan(raw_plan, state)

        plan["depth"] = "low"
        plan["target_words"] = 650
        plan["reference_policy"] = "standard"
        plan["reasoning_policy"] = "evidence_plus_analysis"

        allowed_ids = {
            "direct_answer",
            "research_findings",
            "comparative_analysis",
            "limitations",
            "references",
        }

        plan["modules"] = [
            m for m in plan.get("modules", [])
            if m.get("module_id") in allowed_ids
        ][:5]

        total_importance = sum(
            m.get("importance", 80)
            for m in plan["modules"]
            if m.get("module_id") != "references"
        ) or 1

        for m in plan["modules"]:
            if m.get("module_id") == "references":
                m["target_words"] = 0
            else:
                m["target_words"] = max(
                    90,
                    int(
                        plan["target_words"]
                        * 0.92
                        * m.get("importance", 80)
                        / total_importance
                    ),
                )

        return {
            "report_plan": plan,
            "information_needs": plan.get("information_needs", []),
            "complexity_score": plan.get("complexity_score", 30),
            "report_depth": "low",
            "target_word_count": plan.get("target_words", 650),
            "module_plan": plan.get("modules", []),
            "report_notice": None,
            "target_paper_k": _adaptive_target_paper_k(plan, state),
        }

    query = state.get("query", "")
    evidence_mode = state.get("evidence_mode", "literature")
    understanding = state.get("query_understanding") or {}

    llm = get_llm(temperature=0, task="structured")

    try:
        plan_llm = llm.with_structured_output(ReportPlanLLM).invoke(
            [
                SystemMessage(content=_REPORT_PLAN_SYSTEM.strip()),
                HumanMessage(
                    content=_REPORT_PLAN_PROMPT.format(
                        query=query,
                        response_mode=response_mode,
                        evidence_mode=evidence_mode,
                        understanding=str(understanding)[:3000],
                        catalog=module_catalog_text(),
                    )
                ),
            ],
            config={"timeout": settings.REPORT_PLAN_TIMEOUT},
        )

        if isinstance(plan_llm, dict):
            raw_plan = plan_llm
        else:
            raw_plan = plan_llm.model_dump()

    except Exception as e:
        print(
            f"[report_plan_node] planner failed, using deterministic fallback: "
            f"{type(e).__name__}: {e}"
        )
        raw_plan = default_report_plan(state)

    plan = normalize_report_plan(raw_plan, state)

    answer_spec = state.get("answer_spec") or {}
    if answer_spec:
        plan["answer_outline"] = answer_spec.get("answer_outline") or []
        if (
            "mathematical_derivation" in answer_spec.get("question_types", [])
            and plan.get("epistemic_mode") != "textbook_derivation"
        ):
            plan["epistemic_mode"] = "textbook_derivation"

    target_paper_k = _adaptive_target_paper_k(plan, state)

    return {
        "report_plan": plan,
        "information_needs": plan.get("information_needs", []),
        "complexity_score": plan.get("complexity_score", 50),
        "report_depth": plan.get("depth", "medium"),
        "target_word_count": plan.get(
            "target_words",
            settings.REPORT_TARGET_WORDS_MEDIUM,
        ),
        "module_plan": plan.get("modules", []),
        "report_notice": plan.get("latency_notice"),
        "target_paper_k": target_paper_k,
    }