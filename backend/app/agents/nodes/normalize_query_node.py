from app.agents.state import AgentState
from app.agents.schemas import NormalizedQuery
from app.services.llm_client import get_llm


def normalize_query_node(state: AgentState) -> AgentState:
    llm = get_llm(temperature=0)
    structured_llm = llm.with_structured_output(NormalizedQuery)

    prompt = f"""Convert this user query into the bare technical search term a researcher would use to find the seminal paper on this topic.

User query: {state['query']}

Examples:
"explain RAG" -> "Retrieval-Augmented Generation"
"what is causal XAI" -> "causal explainable AI"
"how does attention work in transformers" -> "attention mechanism transformer"
"""
    result: NormalizedQuery = structured_llm.invoke(prompt)
    return {
        **state,
        "refined_query": result.search_term,
        "is_definitional": result.is_definitional,
    }
