from app.agents.state import AgentState
from app.services.citation_formatter import format_apa


def citation_node(state: AgentState) -> AgentState:
    citations = [format_apa(p) for p in state["ranked_papers"]]
    return {**state, "citations": citations}
