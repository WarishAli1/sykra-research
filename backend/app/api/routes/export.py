import io
import os
import re
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable,
)

from app.models.schemas import PdfExportRequest

router = APIRouter()

EXPORT_DIR = "exports"
os.makedirs(EXPORT_DIR, exist_ok=True)


def _slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[\s_-]+", "-", text)[:60] or "answer"


def _clean_markdown_bold(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    return text


def _split_answer_and_references(answer: str) -> tuple[str, str | None]:
    marker = "\n\n---\n\n**References**"
    if marker.replace("**", "") in answer or "**References**" in answer:
        parts = answer.split("**References**")
        if len(parts) == 2:
            body = parts[0].replace("\n\n---\n\n", "").strip()
            return body, parts[1].strip()
    return answer, None


def _build_standard_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="BodyJustified", parent=styles["BodyText"],
        alignment=TA_JUSTIFY, fontSize=10.5, leading=15, spaceAfter=10,
    ))
    styles.add(ParagraphStyle(
        name="SectionHeading", parent=styles["Heading2"],
        fontSize=13, spaceBefore=14, spaceAfter=6, textColor="#1a1a2e",
    ))
    styles.add(ParagraphStyle(
        name="ReportTitle", parent=styles["Title"], fontSize=18, spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        name="RefEntry", parent=styles["BodyText"],
        fontSize=9, leading=13, leftIndent=18, firstLineIndent=-18, spaceAfter=6,
    ))
    return styles


def _build_latex_style_styles():
    styles = getSampleStyleSheet()
    serif = "Times-Roman"
    serif_bold = "Times-Bold"
    styles.add(ParagraphStyle(
        name="BodyJustified", parent=styles["BodyText"], fontName=serif,
        alignment=TA_JUSTIFY, fontSize=10.5, leading=16, spaceAfter=10,
        firstLineIndent=14,
    ))
    styles.add(ParagraphStyle(
        name="SectionHeading", parent=styles["Heading2"], fontName=serif_bold,
        fontSize=12, spaceBefore=16, spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        name="ReportTitle", parent=styles["Title"], fontName=serif_bold,
        fontSize=16, spaceAfter=4, alignment=1,
    ))
    styles.add(ParagraphStyle(
        name="Abstract", parent=styles["BodyText"], fontName=serif,
        fontSize=9.5, leading=13, alignment=TA_JUSTIFY,
        leftIndent=30, rightIndent=30, spaceAfter=16,
    ))
    styles.add(ParagraphStyle(
        name="RefEntry", parent=styles["BodyText"], fontName=serif,
        fontSize=9, leading=13, leftIndent=18, firstLineIndent=-18, spaceAfter=6,
    ))
    return styles


def _paragraphs_from_body(body: str, styles) -> list:
    flowables = []
    for block in body.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        block = _clean_markdown_bold(block)
        if block.startswith("<b>") and block.count("\n") == 0 and len(block) < 120:
            flowables.append(Paragraph(block.replace("<b>", "").replace("</b>", ""), styles["SectionHeading"]))
        else:
            flowables.append(Paragraph(block, styles["BodyJustified"]))
    return flowables


def _render_pdf(req: PdfExportRequest, latex_style: bool) -> bytes:
    styles = _build_latex_style_styles() if latex_style else _build_standard_styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=LETTER,
        topMargin=0.9 * inch, bottomMargin=0.9 * inch,
        leftMargin=0.9 * inch, rightMargin=0.9 * inch,
    )

    body, inline_refs = _split_answer_and_references(req.answer)
    title = req.title or "Research Assistant — Answer"

    story = [Paragraph(title, styles["ReportTitle"])]

    if latex_style:
        story.append(Spacer(1, 6))
        story.append(HRFlowable(width="100%", thickness=0.5, color="#333333"))
        story.append(Spacer(1, 10))
        first_para = body.split("\n\n")[0].strip()
        if first_para:
            story.append(Paragraph("<b>Abstract.</b> " + _clean_markdown_bold(first_para), styles["Abstract"]))

    story.extend(_paragraphs_from_body(body, styles))

    references = req.references
    if references:
        story.append(Spacer(1, 16))
        story.append(HRFlowable(width="100%", thickness=0.5, color="#888888"))
        story.append(Spacer(1, 8))
        story.append(Paragraph("References", styles["SectionHeading"]))
        for r in references:
            authors = ", ".join(r.authors[:4]) if r.authors else ""
            year = f" ({r.published})" if r.published else ""
            author_part = f"{authors}{year}. " if authors else ""
            entry = f"[{r.id}] {author_part}{r.title}. {r.link}"
            story.append(Paragraph(entry, styles["RefEntry"]))
    elif inline_refs:
        story.append(Spacer(1, 16))
        story.append(HRFlowable(width="100%", thickness=0.5, color="#888888"))
        story.append(Spacer(1, 8))
        story.append(Paragraph("References", styles["SectionHeading"]))
        for line in inline_refs.split("\n"):
            line = line.strip()
            if line:
                story.append(Paragraph(line, styles["RefEntry"]))

    doc.build(story)
    return buf.getvalue()


@router.post("/export/pdf")
def export_pdf(req: PdfExportRequest):
    if not req.answer.strip():
        raise HTTPException(status_code=400, detail="Nothing to export — answer is empty.")

    latex_style = req.format == "latex"
    pdf_bytes = _render_pdf(req, latex_style=latex_style)

    filename = f"{_slugify(req.title or req.session_id)}-{uuid.uuid4().hex[:8]}.pdf"
    out_path = os.path.join(EXPORT_DIR, filename)
    with open(out_path, "wb") as f:
        f.write(pdf_bytes)

    return FileResponse(
        out_path, media_type="application/pdf", filename=filename,
    )