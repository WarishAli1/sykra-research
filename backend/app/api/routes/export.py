import os
import re
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from app.services.filename_service import get_filename
from app.models.schemas import PdfExportRequest
from app.pdf.pdf_renderer import render_answer_pdf

router = APIRouter()

EXPORT_DIR = "exports"
os.makedirs(EXPORT_DIR, exist_ok=True)

CITATION_GROUP_RE = re.compile(r"\[(?:paper_id\s*=\s*)?(\d+(?:\s*,\s*\d+)*)\]")
HEADING_RE = re.compile(r"^(#{1,4})\s+(.*)$")
BULLET_RE = re.compile(r"^\s*[-*•]\s+(.*)$")
NUM_BULLET_RE = re.compile(r"^\s*\d+[.)]\s+(.*)$")
TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")
TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:-]+\|[\s:|-]*$")


def _slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[\s_-]+", "-", text)[:60] or "answer"


@router.post("/export/pdf")
def export_pdf(req: PdfExportRequest):
    if not req.answer.strip():
        raise HTTPException(status_code=400, detail="Nothing to export — answer is empty.")
    
    latex_style = req.format == "latex"
    title = req.title or "Research Assistant - Answer"
    references = [r.model_dump() if hasattr(r, "model_dump") else r for r in req.references] if req.references else None
    
    try:
        pdf_bytes = render_answer_pdf(
            answer=req.answer,
            title=title,
            references=references,
            chart_path=req.chart_path,
            latex_style=latex_style,
        )
    except FileNotFoundError as e:
        print(f"[export] {e}")
        raise HTTPException(
            status_code=500,
            detail="PDF export is temporarily unavailable (missing math rendering assets).",
        )
    except Exception as e:
        print(f"[export] PDF render failed: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail="Could not generate PDF. Please try again.")
    
    # Use KeyBERT filename if available
    slug = get_filename(req.turn_id) if req.turn_id else None
    if not slug:
        slug = _slugify(req.title or req.session_id)
        
    filename = f"{slug}-{uuid.uuid4().hex[:8]}.pdf"
    out_path = os.path.join(EXPORT_DIR, filename)
    with open(out_path, "wb") as f:
        f.write(pdf_bytes)
        
    return FileResponse(
        out_path, media_type="application/pdf", filename=filename,
    )