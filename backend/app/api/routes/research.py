import asyncio
import uuid
from uuid import UUID
from fastapi import HTTPException
from sqlalchemy import select
from app.db.models import LibraryPaper
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession
from app.auth import get_current_user
from app.db.database import get_db
from app.db.models import User
from app.services.ownership import require_research_session
from app.services import graph_builder
from app.agents.graph import research_graph, run_enrichment
from app.services.graph_store import graph_store

router = APIRouter()

def _chat_links(db, user, rs, chat_id: str | None):
    """Links of papers saved in this chat; None means no chat filter."""
    if not chat_id:
        return None
    try:
        cid = UUID(chat_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid chat identifier.")
    return list(db.scalars(select(LibraryPaper.link).where(
        LibraryPaper.user_id == user.id,
        LibraryPaper.session_id == rs.id,
        LibraryPaper.chat_id == cid,
    )))

class ResearchRequest(BaseModel):
    query: str
    session_id: str | None = None

class ResearchResponse(BaseModel):
    answer: str
    session_id: str
    papers_processed: int
    paper_links: list[str] = []

class GraphViewRequest(BaseModel):
    scope: str = "conversation"
    chat_id: str | None = None
    paper_links: list[str] | None = None
    max_year: int | None = None


@router.post("/research", response_model=ResearchResponse)
async def research(
    req: ResearchRequest,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    session_id = req.session_id or str(uuid.uuid4())
    require_research_session(db, user, session_id, create=True)

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

        "answer_spec": None,
        "source_plan": None,
        "evidence_matrix": {},
        "citation_audit": [],
        "math_verification": None,
        "primary_source_present": False,

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

        "report_plan": None,
        "information_needs": [],
        "complexity_score": 0,
        "report_depth": "high",
        "target_word_count": 0,
        "module_plan": [],
        "module_evidence_map": {},
        "section_outputs": [],
        "dynamic_confidence": None,
        "cited_paper_ids": [],
        "report_notice": None,

        "query_embedding": None,

        "target_paper_k": 0,
        "preview_answer": "",
        "preview_streamed": False,
        "search_cache_hit": False,
    }

    final_state = await research_graph.ainvoke(initial_state)
    final_state = await asyncio.to_thread(run_enrichment, final_state)
    ranked_papers = final_state.get("ranked_papers", [])
    cited_papers = final_state.get("citations", []) 
    
    paper_links = list({
        p.get("link") for p in (ranked_papers + cited_papers) 
        if isinstance(p, dict) and p.get("link")
    })
    return ResearchResponse(
        answer=final_state.get("final_answer", ""),
        session_id=session_id,
        papers_processed=len(final_state.get("ranked_papers", [])),
        paper_links=paper_links,
    )

class GraphQueryRequest(BaseModel):
    q: str
    chat_id: str | None = None

class GraphPathRequest(GraphViewRequest):
    a: str
    b: str

@router.post("/graph/{session_id}/view")
def graph_view(session_id: str, req: GraphViewRequest, user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    rs = require_research_session(db, user, session_id)
    enriched = graph_builder.get_enriched(session_id)
    links = req.paper_links if req.scope == "message" else _chat_links(db, user, rs, req.chat_id)
    view = graph_builder.filter_view(enriched, links, req.max_year)
    return {**view, "legend": enriched["legend"], "rel": enriched["rel"],
            "global_stats": enriched["stats"]}

@router.post("/graph/{session_id}/path")
def graph_path(session_id: str, req: GraphPathRequest, user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    rs = require_research_session(db, user, session_id)
    enriched = graph_builder.get_enriched(session_id)
    links = req.paper_links if req.scope == "message" else _chat_links(db, user, rs, req.chat_id)
    return {"path": graph_builder.shortest_path(enriched, req.a, req.b, links, req.max_year)}

@router.get("/graph/{session_id}/suggest")
def graph_suggest(session_id: str, q: str = "", chat_id: str | None = None, user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    rs = require_research_session(db, user, session_id)
    enriched = graph_builder.get_enriched(session_id)
    links = _chat_links(db, user, rs, chat_id)
    if links is not None:
        enriched = {**enriched, **graph_builder.filter_view(enriched, links)}
    return {"matches": graph_builder.suggest_nodes(enriched, q)}
    

@router.post("/graph/{session_id}/query")
def graph_query(session_id: str, req: GraphQueryRequest, user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    rs = require_research_session(db, user, session_id)
    links = _chat_links(db, user, rs, req.chat_id)
    matches = graph_builder.semantic_query(session_id, req.q, top_k=30)
    if links is not None:
        allowed = {n["id"] for n in graph_builder.filter_view(graph_builder.get_enriched(session_id), links)["nodes"]}
        matches = [m for m in matches if m["id"] in allowed]
    return {"matches": matches[:6]}


@router.get("/graph/{session_id}/ensure")
def ensure_graph(session_id: str, force: bool = False, user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """Single on-demand call used by the Explore view.
    Builds the session graph the first time (few seconds), cached afterwards."""
    require_research_session(db, user, session_id)
    return graph_builder.build_session_graph(session_id, force=force)


@router.get("/graph/{session_id}/clusters")
def macro_view(session_id: str, chat_id: str | None = None, user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    rs = require_research_session(db, user, session_id)
    return {"clusters": graph_builder.get_clusters(session_id, _chat_links(db, user, rs, chat_id))}


@router.get("/graph/{session_id}/contradictions")
def contradictions(session_id: str, user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    require_research_session(db, user, session_id)
    return {"contradictions": graph_builder.get_contradictions(session_id)}


@router.get("/graph/paper/focus")
def focus_mode(paper_link: str, user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    return graph_store.get_node_neighborhood(paper_link)



@router.get("/graph/{session_id}/full")
def full_graph(session_id: str, user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    require_research_session(db, user, session_id)
    return graph_store.get_full_graph(session_id)


@router.get("/graph/{session_id}/turn/{turn_id}/full")
def turn_graph(session_id: str, turn_id: str, user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    require_research_session(db, user, session_id)
    return graph_store.get_turn_graph(session_id, turn_id)