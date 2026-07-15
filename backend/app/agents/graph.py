import time
import functools

from langgraph.graph import StateGraph, END
from app.agents.state import AgentState
from app.agents.nodes.search_node import search_node
from app.agents.nodes.retrieve_uploaded_node import retrieve_uploaded_node
from app.agents.nodes.validate_node import validate_node
from app.agents.nodes.rank_node import rank_node
from app.agents.nodes.summarize_node import summarize_node
from app.agents.nodes.citation_node import citation_node
from app.agents.nodes.graph_write_node import graph_write_node


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


def build_graph():
    graph = StateGraph(AgentState)

    graph.set_entry_point("search")
    graph.add_node("search", timed("search")(search_node))
    graph.add_node("retrieve_uploaded", timed("retrieve_uploaded")(retrieve_uploaded_node))
    graph.add_node("validate", timed("validate")(validate_node))
    graph.add_node("rank", timed("rank")(rank_node))
    graph.add_node("summarize", timed("summarize")(summarize_node))
    graph.add_node("cite", timed("cite")(citation_node))
    graph.add_node("graph_write", timed("graph_write")(graph_write_node))

    graph.add_edge("search", "retrieve_uploaded")
    graph.add_edge("retrieve_uploaded", "validate")
    graph.add_edge("validate", "rank")
    graph.add_edge("rank", "summarize")
    graph.add_edge("summarize", "cite")
    graph.add_edge("cite", "graph_write")
    graph.add_edge("graph_write", END)

    return graph.compile()


research_graph = build_graph()
