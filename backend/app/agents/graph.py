from langgraph.graph import StateGraph, END
from app.agents.state import AgentState
from app.agents.nodes.normalize_query_node import normalize_query_node
from app.agents.nodes.search_node import search_node
from app.agents.nodes.validate_node import validate_node
from app.agents.nodes.rank_node import rank_node
from app.agents.nodes.retry_node import retry_node
from app.agents.nodes.fetch_pdf_node import fetch_pdf_node
from app.agents.nodes.summarize_node import summarize_node
from app.agents.nodes.citation_node import citation_node


def route_after_rank(state: AgentState) -> str:
    if state.get("needs_retry"):
        return "retry"
    return "fetch_pdf"


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("normalize_query", normalize_query_node)
    graph.add_node("search", search_node)
    graph.add_node("validate", validate_node)
    graph.add_node("rank", rank_node)
    graph.add_node("retry", retry_node)
    graph.add_node("fetch_pdf", fetch_pdf_node)
    graph.add_node("summarize", summarize_node)
    graph.add_node("cite", citation_node)

    graph.set_entry_point("normalize_query")
    graph.add_edge("normalize_query", "search")
    graph.add_edge("search", "validate")
    graph.add_edge("validate", "rank")

    graph.add_conditional_edges(
        "rank",
        route_after_rank,
        {"retry": "retry", "fetch_pdf": "fetch_pdf"},
    )

    graph.add_edge("retry", "search")
    graph.add_edge("fetch_pdf", "summarize")
    graph.add_edge("summarize", "cite")
    graph.add_edge("cite", END)

    return graph.compile()


research_graph = build_graph()
