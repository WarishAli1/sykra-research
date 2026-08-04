import asyncio
import functools
import time
from langgraph.graph import StateGraph, END
from app.agents.state import AgentState
from app.agents.nodes.plan_query_node import plan_query_node
from app.agents.nodes.report_plan_node import report_plan_node
from app.agents.nodes.search_node import search_node
from app.agents.nodes.retrieve_uploaded_node import retrieve_uploaded_node
from app.agents.nodes.validate_node import validate_node
from app.agents.nodes.rank_node import rank_node
from app.agents.nodes.preview_node import preview_node
from app.agents.nodes.summarize_node import summarize_node
from app.agents.nodes.critique_node import critique_node
from app.agents.nodes.revise_node import revise_node
from app.agents.nodes.compare_node import compare_node
from app.agents.nodes.citation_node import citation_node

def timed(name):
    def decorator(fn):
        if asyncio.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def async_wrapper(state):
                t0 = time.time()
                result = await fn(state)
                print(f"[timing] {name}: {round(time.time() - t0, 2)}s")
                return result
            return async_wrapper

        @functools.wraps(fn)
        def sync_wrapper(state):
            t0 = time.time()
            result = fn(state)
            print(f"[timing] {name}: {round(time.time() - t0, 2)}s")
            return result
        return sync_wrapper
    return decorator

def after_critique_node(state):
    return {
        "revision_count": state.get("revision_count", 0)
    }

def answer_ready_node(state):
    return {
        "preview_streamed": state.get("preview_streamed", False),
    }

def route_after_critique(state: AgentState) -> str:
    if (
        state.get("needs_revision")
        and state.get("revision_instruction")
        and state.get("revision_count", 0) <= 1
    ):
        return "revise"
    return "after_critique"

def build_graph():
    graph = StateGraph(AgentState)

    graph.set_entry_point("plan_query")

    graph.add_node("plan_query", timed("plan_query")(plan_query_node))
    graph.add_node("plan_report", timed("plan_report")(report_plan_node))
    graph.add_node("search", timed("search")(search_node))
    graph.add_node("retrieve_uploaded", timed("retrieve_uploaded")(retrieve_uploaded_node))
    graph.add_node("validate", timed("validate")(validate_node))
    graph.add_node("rank", timed("rank")(rank_node))
    graph.add_node("quick_preview", timed("quick_preview")(preview_node))
    graph.add_node("summarize", timed("summarize")(summarize_node))
    graph.add_node("critique", timed("critique")(critique_node))
    graph.add_node("revise", timed("revise")(revise_node))
    graph.add_node("after_critique", after_critique_node)
    graph.add_node("cite", timed("cite")(citation_node))
    graph.add_node("answer_ready", answer_ready_node)

    graph.add_edge("plan_query", "plan_report")
    graph.add_edge("plan_query", "search")
    graph.add_edge(["plan_report", "search"], "retrieve_uploaded")
    graph.add_edge("retrieve_uploaded", "validate")
    graph.add_edge("validate", "rank")
    graph.add_edge("rank", "quick_preview")
    graph.add_edge("quick_preview", "summarize")
    graph.add_edge("summarize", "critique")

    graph.add_conditional_edges(
        "critique",
        route_after_critique,
        {
            "revise": "revise",
            "after_critique": "after_critique",
        },
    )
    graph.add_edge("revise", "after_critique")
    graph.add_edge("after_critique", "cite")
    graph.add_edge("cite", "answer_ready")
    graph.add_edge("answer_ready", END)

    return graph.compile()

research_graph = build_graph()

def run_enrichment(state: dict) -> dict:
    """
    Run non-critical enrichment after the answer has been streamed.
    The knowledge graph is now built on-demand when the user opens Explore Graph,
    so graph_write_node has been removed from here to make chat much faster.
    """
    state_copy = dict(state)
    updates = {}
    
    try:
        result = compare_node(state_copy)
        if isinstance(result, dict):
            updates.update(result)
    except Exception as e:
        print(f"[enrichment] compare failed: {type(e).__name__}: {e}")
        
    updates.pop("final_answer", None)
    state.update(updates)
    return state