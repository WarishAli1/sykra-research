from app.agents.state import AgentState
from app.services.vector_store import vector_store


def ingest_node(state: AgentState) -> AgentState:
    session_id = state.get("session_id", "default")
    for paper in state["ranked_papers"]:
        vector_store.upsert_paper(paper, session_id)
    return state
