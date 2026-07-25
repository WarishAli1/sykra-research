import uuid
from fastapi import APIRouter
from pydantic import BaseModel
from app.services.graph_store import graph_store

router = APIRouter()


class ResearchRequest(BaseModel):
    query: str
    session_id: str | None = None


class ResearchResponse(BaseModel):
    answer: str
    session_id: str
    papers_processed: int


@router.post("/research", response_model=ResearchResponse)
def research(req: ResearchRequest):
    session_id = req.session_id or str(uuid.uuid4())

    graph_store.clear_session(session_id)

    initial_state = {
        "query": req.query,
        "session_id": session_id,
        "turn_id": str(uuid.uuid4()),
        "evidence_mode": "literature",
        "response_mode": "researched",
        "refined_query": None,
        "search_terms": [],
        "search_queries": [],
        "query_understanding": None,
        "query_plan": None,
        "is_definitional": False,
        "likely_cs_relevant": True,
        "domain_full": None,
        "domain_keywords": [],
        "mandatory_domain_keywords": None,
        "search_attempts": 0,
        "max_search_attempts": 2,
        "raw_search_results": [],
        "extracted_papers": [],
        "ranked_papers": [],
        "summaries": {},
        "uploaded_context": [],
        "term_coverage": {},
        "papers_below_threshold": 0,
        "final_answer": "",
        "coverage_gaps": [],
        "domain_caveat": None,
        "citations": [],
        "references": [],
        "needs_retry": False,
        "error": None,
        "validation_results": [],
        "graph_contradictions": [],
        "graph_entities": [],
        "conversation_history": [],
        "low_confidence_results": False,
        "chart_spec_raw": None,
        "chart_url": None,
        "comparison_table_markdown": None,
        "comparison_table_caption": None,
        "needs_revision": False,
        "revision_count": 0,
        "revision_instruction": None,
    }
    final_state = research_graph.invoke(initial_state)

    return ResearchResponse(
        answer=final_state["final_answer"],
        session_id=session_id,
        papers_processed=len(final_state.get("ranked_papers", [])),
    )


@router.get("/graph/{session_id}/clusters")
def macro_view(session_id: str):
    return {"clusters": graph_store.get_clusters(session_id)}


@router.get("/graph/paper/focus")
def focus_mode(paper_link: str):
    return graph_store.get_node_neighborhood(paper_link)


@router.get("/graph/{session_id}/contradictions")
def contradictions(session_id: str):
    return {"contradictions": graph_store.get_contradictions(session_id)}


@router.get("/graph/{session_id}/papers")
def session_papers(session_id: str):
    return {"papers": graph_store.get_session_papers(session_id)}


@router.get("/graph/{session_id}/full")
def full_graph(session_id: str):
    return graph_store.get_full_graph(session_id)


@router.get("/graph/{session_id}/turn/{turn_id}/full")
def turn_graph(session_id: str, turn_id: str):
    """Message-scoped graph — this route was missing entirely, which is the
    actual cause of the 404 on the 'view graph of this message' button.
    Requires graph_store.get_turn_graph() and graph_write_node.py passing
    turn_id into upsert_paper() — see those files if not already updated."""
    return graph_store.get_turn_graph(session_id, turn_id)
