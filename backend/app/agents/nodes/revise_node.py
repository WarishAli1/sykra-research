from langchain_core.messages import SystemMessage, HumanMessage
from app.agents.state import AgentState
from app.services.llm_client import get_llm


def revise_node(state: AgentState) -> AgentState:
    if not state.get("needs_revision"):
        return {}

    llm = get_llm(temperature=0)
    draft = state.get("final_answer", "")
    instruction = state.get("revision_instruction", "")

    prompt = f"""Revise this answer to fix ONE specific gap. Do not rewrite
sections that are already fine — make the minimal edit needed.

GAP TO FIX: {instruction}

CURRENT ANSWER:
{draft}

Return the full revised answer with the gap addressed."""

    try:
        response = llm.invoke([
            SystemMessage(content="You make minimal, targeted edits to research answers. Return the full revised text only."),
            HumanMessage(content=prompt),
        ], config={"timeout": 30})
        return {"final_answer": response.content.strip()}
    except Exception as e:
        print(f"[revise_node] failed, keeping original draft: {e}")
        return {}
