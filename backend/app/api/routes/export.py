import os
import re
import uuid
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from app.services.filename_service import get_filename, generate_filename
from app.models.schemas import PdfExportRequest
from app.pdf.pdf_renderer import render_answer_pdf
from app.pdf.pdf_template import prettify_title

router = APIRouter()
EXPORT_DIR = "exports"
os.makedirs(EXPORT_DIR, exist_ok=True)


def _slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[\s_-]+", "-", text)[:60] or "answer"


def _prose_for_title(answer: str) -> str:
    """Strip structural lines (headings, 'Evidence:' labels, [n] refs) so
    KeyBERT extracts keyphrases from pure content prose only."""
    lines = []
    for line in (answer or "").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("!["):
            continue
        if s.endswith(":") and len(s) <= 48:        
            continue
        if s.startswith("[") and "]" in s[:6]:     
            continue
        lines.append(s)
    return "\n".join(lines)


def _is_section_label(title: str, answer: str) -> bool:
    """Structural check (no lists): True if the title exactly matches a
    heading / label line inside the answer, e.g. 'Direct Answer'."""
    t = (title or "").strip().lower()
    if not t or len(t) > 48:
        return False
    for line in (answer or "").splitlines():
        body = line.strip().lower().lstrip("#* ").rstrip(":").strip()
        if body == t:
            return True
    return False


@router.post("/export/pdf")
def export_pdf(req: PdfExportRequest):
    if not req.answer.strip():
        raise HTTPException(status_code=400, detail="Nothing to export — answer is empty.")
    latex_style = req.format == "latex"

    slug = get_filename(req.turn_id) if req.turn_id else None
    if not slug:
        slug = generate_filename(
            req.turn_id or uuid.uuid4().hex, _prose_for_title(req.answer)
        )

    if slug and slug != "research-answer":
        title = prettify_title(slug, source=req.answer)
    else:
        raw = (req.title or "").strip()
        if raw and not _is_section_label(raw, req.answer):
            title = prettify_title(raw, source=req.answer)
        else:
            title = "Research Report"

    references = [
        r.model_dump() if hasattr(r, "model_dump") else r
        for r in req.references
    ] if req.references else None

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
        raise HTTPException(status_code=500,
                            detail="PDF export is temporarily unavailable (missing math rendering assets).")
    except Exception as e:
        print(f"[export] PDF render failed: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail="Could not generate PDF. Please try again.")

    filename = f"{slug if slug and slug != 'research-answer' else _slugify(title)}-{uuid.uuid4().hex[:8]}.pdf"
    out_path = os.path.join(EXPORT_DIR, filename)
    with open(out_path, "wb") as f:
        f.write(pdf_bytes)
    return FileResponse(out_path, media_type="application/pdf", filename=filename)