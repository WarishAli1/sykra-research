import time
import functools

from langgraph.graph import StateGraph, END
from app.agents.state import AgentState
from app.agents.nodes.normalize_query_node import normalize_query_node
from app.agents.nodes.search_node import search_node
from app.agents.nodes.validate_node import validate_node
from app.agents.nodes.rank_node import rank_node
from app.agents.nodes.retry_node import retry_node
from app.agents.nodes.fetch_pdf_node import fetch_pdf_node
from app.agents.nodes.coverage_check_node import coverage_check_node
from app.agents.nodes.summarize_node import summarize_node
from app.agents.nodes.ingest_node import ingest_node
from app.agents.nodes.citation_node import citation_node


def timed(name):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(state):
            t0 = time.time()
            result = fn(state)
            print(f"[timing] {name}: {round(time.time() - t0, 2)}s")
            return result
        return wrapper
    return decorator


def route_after_rank(state: AgentState) -> str:
    if state.get("needs_retry"):
        return "retry"
    return "fetch_pdf"


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("normalize_query", timed("normalize_query")(normalize_query_node))
    graph.add_node("search", timed("search")(search_node))
    graph.add_node("validate", timed("validate")(validate_node))
    graph.add_node("rank", timed("rank")(rank_node))
    graph.add_node("retry", timed("retry")(retry_node))
    graph.add_node("fetch_pdf", timed("fetch_pdf")(fetch_pdf_node))
    graph.add_node("coverage_check", timed("coverage_check")(coverage_check_node))
    graph.add_node("summarize", timed("summarize")(summarize_node))
    graph.add_node("ingest", timed("ingest")(ingest_node))
    graph.add_node("cite", timed("cite")(citation_node))

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
    graph.add_edge("fetch_pdf", "coverage_check")
    graph.add_edge("coverage_check", "summarize")
    graph.add_edge("summarize", "ingest")
    graph.add_edge("ingest", "cite")
    graph.add_edge("cite", END)

    return graph.compile()


research_graph = build_graph()
