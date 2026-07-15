import uuid
from fastapi import APIRouter
from pydantic import BaseModel

from app.agents.graph import research_graph
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
        "include_uploaded": False,
        "upload_mode": "none",
        "refined_query": None,
        "search_terms": [],
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
        "needs_retry": False,
        "error": None,
        "validation_results": [],
        "graph_contradictions": [],
        "graph_entities": [],
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
