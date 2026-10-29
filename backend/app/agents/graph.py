import asyncio
import functools
import time

from langgraph.graph import StateGraph, END

from app.agents.state import AgentState
from app.agents.nodes.plan_query_node import plan_query_node
from app.agents.nodes.answer_spec_node import answer_spec_node
from app.agents.nodes.retrieval_plan_node import retrieval_plan_node
from app.agents.nodes.report_plan_node import report_plan_node
from app.agents.nodes.search_node import search_node
from app.agents.nodes.retrieve_uploaded_node import retrieve_uploaded_node
from app.agents.nodes.validate_node import validate_node
from app.agents.nodes.rank_node import rank_node
from app.agents.nodes.summarize_node import summarize_node
from app.agents.nodes.verify_answer_node import verify_answer_node
from app.agents.nodes.critique_node import critique_node
from app.agents.nodes.revise_node import revise_node
from app.agents.nodes.compare_node import compare_node
from app.agents.nodes.citation_node import citation_node
from app.agents.nodes.ledger_node import ledger_node
from app.agents.nodes.report_structure_node import ensure_report_structure
from app.agents.nodes.report_validate_node import report_validate_node, route_after_report_validate
from app.agents.nodes.report_finalize_node import report_finalize_node
from app.agents.nodes.report_source_node import (
    report_source_node, report_evidence_gate_node,
    route_after_report_evidence_gate, report_gap_search_node,
)
from app.agents.nodes.report_writer_node import report_writer_node, report_revise_node

ENABLE_RESEARCH_CRITIQUE = True


def timed(name: str):
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
        "revision_count": state.get("revision_count", 0),
    }


def answer_ready_node(state):
    return {
        "preview_streamed": state.get("preview_streamed", False),
    }


def plan_report_dispatch(state):
    """Chat answers always plan modules; report runs arrive with a user-approved
    structure already in state (Report Studio)."""
    base = report_plan_node(state)
    if not state.get("report_mode_enabled"):
        return base
    merged = {**state, **base}
    return {**base, **ensure_report_structure(merged)}


def route_after_rank(state: AgentState) -> str:
    return "report_source" if state.get("report_mode_enabled") else "build_ledger"


def _needs_verification(state: AgentState) -> bool:
    """
    Run expensive verification only for higher-risk researched answers.
    """
    answer_spec = state.get("answer_spec") or {}
    
    if state.get("response_mode") in ("researched", "graph_research"):
        return True

    if answer_spec.get("equation_verification_required"):
        return True

    if answer_spec.get("primary_source_required"):
        return True

    if answer_spec.get("quantitative_required"):
        return True

    try:
        difficulty = int(answer_spec.get("difficulty_level", 3))
    except Exception:
        difficulty = 3

    if difficulty >= 4:
        return True

    return False


def route_after_summarize(state: AgentState) -> str:
    """
    Normal mode goes directly to citation assembly.

    Researched mode:
    - high-risk answers go through verify_claims
    - normal researched answers go directly to critique
    """
    if state.get("response_mode") == "normal":
        return "cite"
    if _needs_verification(state):
        return "verify_claims"
    return "critique"


def route_after_verify(state: AgentState) -> str:
    if state.get("response_mode") == "normal":
        return "cite"

    if not ENABLE_RESEARCH_CRITIQUE:
        return "cite"

    cancel_check = state.get("_cancel_check")
    if cancel_check and cancel_check():
        return "cite"

    return "critique"


def route_after_critique(state: AgentState) -> str:
    if state.get("response_mode") == "normal":
        return "after_critique"

    cancel_check = state.get("_cancel_check")
    if cancel_check and cancel_check():
        return "after_critique"

    if (
        state.get("needs_revision")
        and state.get("revision_instruction")
        and state.get("revision_count", 0) <= 1
        and state.get("revision_section_ids")
    ):
        return "revise"

    return "after_critique"


def build_graph():
    graph = StateGraph(AgentState)
    graph.set_entry_point("plan_query")

    graph.add_node("plan_query", timed("plan_query")(plan_query_node))
    graph.add_node("answer_spec_node", timed("answer_spec_node")(answer_spec_node))
    graph.add_node(
        "build_retrieval_plan",
        timed("retrieval_plan")(retrieval_plan_node),
    )
    graph.add_node("plan_report", timed("plan_report")(plan_report_dispatch))
    graph.add_node("search", timed("search")(search_node))
    graph.add_node(
        "retrieve_uploaded",
        timed("retrieve_uploaded")(retrieve_uploaded_node),
    )
    graph.add_node("validate", timed("validate")(validate_node))
    graph.add_node("rank", timed("rank")(rank_node))
    graph.add_node("summarize", timed("summarize")(summarize_node))
    graph.add_node("verify_claims", timed("verify_claims")(verify_answer_node))
    graph.add_node("critique", timed("critique")(critique_node))
    graph.add_node("revise", timed("revise")(revise_node))
    graph.add_node("after_critique", after_critique_node)
    graph.add_node("cite", timed("cite")(citation_node))
    graph.add_node("answer_ready", answer_ready_node)
    graph.add_node("build_ledger", timed("ledger")(ledger_node))
    graph.add_node("report_source", timed("report_source")(report_source_node))
    graph.add_node(
        "report_evidence_gate",
        timed("report_evidence_gate")(report_evidence_gate_node),
    )
    graph.add_node(
        "report_gap_search",
        timed("report_gap_search")(report_gap_search_node),
    )
    graph.add_node("report_writer", timed("report_writer")(report_writer_node))
    graph.add_node("report_validate", timed("report_validate")(report_validate_node))
    graph.add_node("report_revise", timed("report_revise")(report_revise_node))
    graph.add_node("report_finalize", timed("report_finalize")(report_finalize_node))
    graph.add_edge("plan_query", "answer_spec_node")
    graph.add_edge("answer_spec_node", "build_retrieval_plan")
    graph.add_edge("build_retrieval_plan", "plan_report")
    graph.add_edge("build_retrieval_plan", "search")
    graph.add_edge(["plan_report", "search"], "retrieve_uploaded")
    graph.add_edge("retrieve_uploaded", "validate")
    graph.add_edge("validate", "rank")
    graph.add_conditional_edges(
        "rank", route_after_rank,
        {"report_source": "report_source", "build_ledger": "build_ledger"},
    )
    graph.add_edge("build_ledger", "summarize")
    graph.add_edge("report_source", "report_evidence_gate")
    graph.add_conditional_edges(
        "report_evidence_gate",
        route_after_report_evidence_gate,
        {
            "retrieve_uploaded": "retrieve_uploaded",
            "report_gap_search": "report_gap_search",
            "report_writer": "report_writer",
        },
    )
    graph.add_edge("report_gap_search", "validate")
    graph.add_edge("report_writer", "report_validate")
    graph.add_conditional_edges(
        "report_validate",
        route_after_report_validate,
        {"revise": "report_revise", "finalize": "report_finalize"},
    )
    graph.add_edge("report_revise", "report_validate")
    graph.add_edge("report_finalize", "cite")
    graph.add_conditional_edges(
        "summarize",
        route_after_summarize,
        {
            "verify_claims": "verify_claims",
            "critique": "critique",
            "cite": "cite",
        },
    )

    graph.add_conditional_edges(
        "verify_claims",
        route_after_verify,
        {
            "critique": "critique",
            "cite": "cite",
        },
    )

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
    Skip completely for normal mode to protect latency.
    """
    if state.get("response_mode") == "normal" or state.get("report_mode_enabled"):
        return state

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