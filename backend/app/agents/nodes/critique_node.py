from langchain_core.messages import SystemMessage, HumanMessage

from app.agents.state import AgentState
from app.agents.schemas import ReportCoverageCheck
from app.services.llm_client import get_llm
from app.config import settings


_MAX_REVISIONS = 1
_MIN_MODULES_FOR_CRITIQUE = 4 


_CRITIQUE_PROMPT = """Check whether this draft answer fully addresses the user's query and planned report structure.

ORIGINAL QUERY:
{query}

PLANNED INFORMATION NEEDS:
{information_needs}

PLANNED MODULES:
{modules}

DRAFT ANSWER:
{draft}

Check specifically for:
1. Did the draft address every specific detail/constraint stated in the query?
2. Did it cover the required planned modules, or explicitly state when evidence is unavailable?
3. Did it silently drop an information need?
4. Did it substitute an unstated assumption without flagging it?

Do NOT nitpick style, length, or formatting.
Only check query coverage, module coverage, and unflagged assumptions.

Return a ReportCoverageCheck JSON object.
"""


def critique_node(state: AgentState) -> AgentState:
    depth = state.get("report_depth")

    if not depth:
        response_mode = state.get("response_mode", "normal")
        depth = "high" if response_mode in ("researched", "graph_research") else "low"

    if depth == "low":
        return {"needs_revision": False}

    if depth == "medium" and state.get("response_mode", "normal") == "normal":
        return {"needs_revision": False}

    revisions_done = state.get("revision_count", 0)
    if revisions_done >= _MAX_REVISIONS:
        return {"needs_revision": False}

    draft = state.get("final_answer", "")
    query = state.get("query", "")

    if not draft or not query:
        return {"needs_revision": False}

    if len(draft.strip()) < 250:
        return {"needs_revision": False}

    plan = state.get("report_plan") or {}
    information_needs = plan.get("information_needs", [])
    modules = [m.get("title", m.get("module_id", "")) for m in plan.get("modules", [])]

    generative_module_count = sum(
        1 for m in plan.get("modules", [])
        if m.get("module_id") not in ("references", "confidence_uncertainty")
    )
    if generative_module_count < _MIN_MODULES_FOR_CRITIQUE:
        return {"needs_revision": False}

    llm = get_llm(temperature=0, task="fast")

    try:
        check = llm.with_structured_output(ReportCoverageCheck).invoke(
            [
                SystemMessage(content="Respond with ONLY a function call to ReportCoverageCheck."),
                HumanMessage(
                    content=_CRITIQUE_PROMPT.format(
                        query=query,
                        information_needs=", ".join(information_needs) or "none",
                        modules=", ".join(modules) or "none",
                        draft=draft[:7000],
                    )
                ),
            ],
            config={"timeout": settings.REPORT_CRITIQUE_TIMEOUT},
        )

        if isinstance(check, dict):
            check = ReportCoverageCheck.model_validate(check)

    except Exception as e:
        print(f"[critique_node] check failed, passing through: {type(e).__name__}: {e}")
        return {"needs_revision": False}

    if check.fully_covers_query:
        return {"needs_revision": False}

    missing = check.missing_or_assumed or []
    missing_modules = check.missing_modules or []
    instruction = (check.revision_instruction or "").strip()

    if not instruction:
        parts = []
        if missing:
            parts.append("Explicitly address or flag these missing points: " + "; ".join(missing))
        if missing_modules:
            parts.append("Cover or explicitly explain missing modules: " + "; ".join(missing_modules))

        if not parts:
            return {"needs_revision": False}

        instruction = " ".join(parts)

    print(f"[critique_node] coverage gap found: missing={missing}, missing_modules={missing_modules}")

    return {
        "needs_revision": True,
        "revision_instruction": instruction,
        "revision_count": revisions_done + 1,
    }