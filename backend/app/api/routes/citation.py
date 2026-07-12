from fastapi import APIRouter, HTTPException

from app.models.schemas import CitationExportRequest, CitationExportResponse
from app.services.vector_store import vector_store
from app.services.citation_formatter import format_citations

router = APIRouter()


@router.post("/citations/export", response_model=CitationExportResponse)
def export_citations(req: CitationExportRequest):
    if req.style not in ("apa", "ieee", "bibtex"):
        raise HTTPException(status_code=400, detail="style must be one of: apa, ieee, bibtex")

    if req.paper_titles:
        matched = vector_store.find_papers_by_title(req.paper_titles, req.session_id)
    else:
        matched = vector_store.get_session_papers(req.session_id)

    if not matched:
        raise HTTPException(status_code=404, detail="No papers found for this session/selection.")

    citations = format_citations(matched, style=req.style)
    return CitationExportResponse(style=req.style, citations=citations)
