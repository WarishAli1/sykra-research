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
You are a research report planner for a flagship domain-agnostic research assistant.

Your job is NOT to answer the question.
Your job is to decide what kind of report should be generated.

Choose modules from the module library only.

Prefer fewer, high-value modules for simple questions.
Use deeper modules for complex research, design, strategy, forecasting, medical, legal, or decision questions.

Important:
- Do not force a literature-review style for simple explanations.
- Do not force implementation/cost/timeline modules unless the question needs them.
- Always include direct_answer, independent_analysis, limitations, confidence_uncertainty, references.
- For high-stakes domains, add guardrails.

Set depth=low for simple factual/explanatory questions.
Set depth=medium for moderately complex questions.
Set depth=high for genuine research surveys, comparisons, design, strategy, forecasting, or high-stakes decisions.
"""


_REPORT_PLAN_PROMPT = """
USER QUERY:
{query}

RESPONSE MODE REQUESTED BY USER:
{response_mode}

EVIDENCE MODE:
{evidence_mode}

QUERY UNDERSTANDING:
{understanding}

MODULE LIBRARY:
{catalog}

Return a ReportPlanLLM object.

Rules:
- module_id values MUST come from the module library.
- importance is 0-100.
- complexity_score is 0-100.
- depth must be one of: low, medium, high.
- reference_policy should be minimal for simple explanations, standard for normal, research for deep research.
- reasoning_policy should be:
  - evidence_only for strict medical/legal/scientific factual questions,
  - evidence_plus_analysis for most research questions,
  - first_principles_allowed for design/strategy/troubleshooting,
  - speculative_allowed only for forecasting/speculative questions.
- Add domain_guardrails for medical, legal, financial, or safety-critical queries.
- If response_mode is normal, prefer low or medium depth.
- If response_mode is researched or graph_research, prefer high depth.
"""


def _adaptive_target_paper_k(plan: dict, state: AgentState) -> int:
    depth = plan.get("depth", "low")

    if depth == "low":
        target = settings.TOP_K_PAPERS_LOW
    elif depth == "medium":
        target = settings.TOP_K_PAPERS_MEDIUM
    else:
        target = settings.TOP_K_PAPERS_HIGH

    information_needs = [str(x).lower() for x in plan.get("information_needs", [])]

    if any(x in information_needs for x in ("comparison", "compare", "tradeoffs", "trade-off")):
        target += 2

    if any(x in information_needs for x in ("forecast", "future", "prediction", "outlook")):
        target += 1

    if state.get("evidence_mode") in ("uploaded", "blended"):
        target = max(target, settings.TOP_K_PAPERS_MEDIUM)

    target = max(settings.TOP_K_PAPERS_MIN, target)
    target = min(settings.TOP_K_PAPERS_MAX, target)

    return int(target)


def report_plan_node(state: AgentState) -> AgentState:
    query = state.get("query", "")
    response_mode = state.get("response_mode", "normal")
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
                        understanding=str(understanding)[:4000],
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
        print(f"[report_plan_node] planner failed, using deterministic fallback: {type(e).__name__}: {e}")
        raw_plan = default_report_plan(state)

    plan = normalize_report_plan(raw_plan, state)

    target_paper_k = _adaptive_target_paper_k(plan, state)

    return {
        "report_plan": plan,
        "information_needs": plan.get("information_needs", []),
        "complexity_score": plan.get("complexity_score", 50),
        "report_depth": plan.get("depth", "low"),
        "target_word_count": plan.get("target_words", settings.REPORT_TARGET_WORDS_LOW),
        "module_plan": plan.get("modules", []),
        "report_notice": plan.get("latency_notice"),
        "target_paper_k": target_paper_k,
    }