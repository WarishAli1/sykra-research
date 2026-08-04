import asyncio
import uuid

from fastapi import APIRouter
from pydantic import BaseModel
from app.services import graph_builder
from app.agents.graph import research_graph, run_enrichment
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
async def research(req: ResearchRequest):
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

    return ResearchResponse(
        answer=final_state.get("final_answer", ""),
        session_id=session_id,
        papers_processed=len(final_state.get("ranked_papers", [])),
    )

class GraphQueryRequest(BaseModel):
    q: str

@router.post("/graph/{session_id}/query")
def graph_query(session_id: str, req: GraphQueryRequest):
    return {"matches": graph_builder.semantic_query(session_id, req.q)}


@router.get("/graph/{session_id}/ensure")
def ensure_graph(session_id: str, force: bool = False):
    """Single on-demand call used by the Explore view.
    Builds the session graph the first time (few seconds), cached afterwards."""
    return graph_builder.build_session_graph(session_id, force=force)


@router.get("/graph/{session_id}/clusters")
def macro_view(session_id: str):
    return {"clusters": graph_builder.get_clusters(session_id)}


@router.get("/graph/{session_id}/contradictions")
def contradictions(session_id: str):
    return {"contradictions": graph_builder.get_contradictions(session_id)}


@router.get("/graph/paper/focus")
def focus_mode(paper_link: str):
    return graph_store.get_node_neighborhood(paper_link)



@router.get("/graph/{session_id}/full")
def full_graph(session_id: str):
    return graph_store.get_full_graph(session_id)


@router.get("/graph/{session_id}/turn/{turn_id}/full")
def turn_graph(session_id: str, turn_id: str):
    return graph_store.get_turn_graph(session_id, turn_id)