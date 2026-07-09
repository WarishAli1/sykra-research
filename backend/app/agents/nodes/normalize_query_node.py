from langchain_core.messages import SystemMessage, HumanMessage
from app.agents.state import AgentState
from app.agents.schemas import NormalizedQuery
from app.services.llm_client import get_llm


def normalize_query_node(state: AgentState) -> AgentState:
    llm = get_llm(temperature=0)
    structured_llm = llm.with_structured_output(NormalizedQuery)

    prompt = f"""Break this query into 1-3 distinct technical search terms — one per
distinct concept named. If the query is about a single concept, return just one term.

User query: {state['query']}

Examples:
"explain RAG" -> ["Retrieval-Augmented Generation"]
"explain AI agent and LangGraph and LangChain" -> ["AI agent architecture", "LangGraph", "LangChain"]
"compare fine-tuning vs RAG" -> ["fine-tuning language models", "Retrieval-Augmented Generation"]
"""
    messages = [
        SystemMessage(content="You must extract search terms from the user query using the NormalizedQuery function. Return a valid function call with no additional text."),
        HumanMessage(content=prompt),
    ]
    result: NormalizedQuery = structured_llm.invoke(messages)
    return {
        **state,
        "search_terms": result.search_terms,
        "is_definitional": result.is_definitional,
    }
