from langchain_core.messages import SystemMessage, HumanMessage
from app.agents.state import AgentState
from app.agents.schemas import RetryDecision
from app.services.llm_client import get_llm


def retry_node(state: AgentState) -> AgentState:
    llm = get_llm(temperature=0.4)
    structured_llm = llm.with_structured_output(RetryDecision)

    prompt = f"""The search for the query below returned no genuinely relevant papers (top score was below threshold).

Query: {state['query']}

Suggest a better, more specific or differently-phrased search query to try instead.
Set should_retry=false only if you believe no rephrasing would help.
"""
    messages = [
        SystemMessage(content="You must decide whether to retry using the RetryDecision function. Return a valid function call with no additional text."),
        HumanMessage(content=prompt),
    ]
    decision: RetryDecision = structured_llm.invoke(messages)

    return {
        **state,
        "search_terms": [],
        "refined_query": decision.refined_query or state["query"],
        "needs_retry": False,
    }
