from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field
from app.agents.state import AgentState
from app.services.llm_client import get_llm

_MAX_REVISIONS = 1


class QueryCoverageCheck(BaseModel):
    fully_covers_query: bool = Field(
        description="True if every specific detail/constraint in the user's "
                    "query is addressed in the draft (either answered from "
                    "evidence, or explicitly flagged as unaddressed by the "
                    "literature). False if something specific was silently "
                    "dropped or an unstated assumption was silently substituted."
    )
    missing_or_assumed: list[str] = Field(
        default_factory=list,
        description="Specific details from the query that were dropped, or "
                    "assumptions the draft made without flagging them. Empty "
                    "if fully_covers_query is True."
    )
    revision_instruction: str = Field(
        default="",
        description="If fully_covers_query is False, a short, concrete "
                    "instruction for how to fix the draft (e.g. 'explicitly "
                    "note that no retrieved source addresses TP53 status'). "
                    "Empty otherwise."
    )


_CRITIQUE_PROMPT = """Check whether this draft answer fully addresses the user's query.

ORIGINAL QUERY: {query}

DRAFT ANSWER:
{draft}

Check specifically for:
1. Did the draft address every specific detail/constraint stated in the
   query (genotype, condition, named entity, numeric constraint, etc.)?
   If the literature doesn't cover a detail, the draft should say so
   explicitly — silently omitting it is a failure.
2. Did the draft substitute a specific unstated guess for something the
   query left general (e.g. guessing a drug name when the query said
   "a drug")? If so, that assumption must be flagged, not stated as fact.

Do NOT nitpick style, length, or formatting — only check query coverage
and unflagged assumptions.

Return a QueryCoverageCheck JSON object matching the schema exactly."""


def critique_node(state: AgentState) -> AgentState:
    if state.get("response_mode") != "researched":
        return {"needs_revision": False}

    revisions_done = state.get("revision_count", 0)
    if revisions_done >= _MAX_REVISIONS:
        return {"needs_revision": False}

    draft = state.get("final_answer", "")
    query = state.get("query", "")
    if not draft or not query:
        return {"needs_revision": False}

    llm = get_llm(temperature=0, task="light")
    try:
        check = llm.with_structured_output(QueryCoverageCheck).invoke(
            [
                SystemMessage(content="Respond with ONLY a function call to QueryCoverageCheck. No text before or after."),
                HumanMessage(content=_CRITIQUE_PROMPT.format(query=query, draft=draft[:6000])),
            ],
            config={"timeout": 20},
        )
        if isinstance(check, dict):
            check = QueryCoverageCheck.model_validate(check)
    except Exception as e:
        print(f"[critique_node] check failed, passing through: {type(e).__name__}: {e}")
        return {"needs_revision": False}

    if check.fully_covers_query:
        return {"needs_revision": False}

    print(f"[critique_node] coverage gap found: {check.missing_or_assumed}")
    return {
        "needs_revision": True,
        "revision_instruction": check.revision_instruction,
        "revision_count": revisions_done + 1,
    }
