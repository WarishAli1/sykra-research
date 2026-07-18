from fastapi import APIRouter

from app.services.graph_store import graph_store

router = APIRouter()

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