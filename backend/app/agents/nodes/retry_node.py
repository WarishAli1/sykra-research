from app.agents.state import AgentState
from app.agents.schemas import RetryDecision
from app.services.llm_client import get_llm


def retry_node(state: AgentState) -> AgentState:
    llm = get_llm(temperature=0.3)
    structured_llm = llm.with_structured_output(RetryDecision)

    prompt = f"""The search for the query below returned no genuinely relevant papers:

Query: {state['query']}

Suggest a better, more specific or differently-phrased search query to try instead.
Set should_retry=false only if you believe no rephrasing would help.
"""
    decision: RetryDecision = structured_llm.invoke(prompt)

    return {
        **state,
        "refined_query": decision.refined_query or state["query"],
        "needs_retry": False,
    }
