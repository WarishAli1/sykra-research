import io
import os
import re
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable,
    Table, TableStyle, ListFlowable, ListItem,
)

from app.models.schemas import PdfExportRequest

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


def _inline_markdown(text: str) -> str:
    """Convert a subset of inline markdown to ReportLab-safe mini-markup."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = (text
        .replace("\u2011", "-")
        .replace("\u2010", "-") 
        .replace("\u2013", "-")
        .replace("\u2014", "--")
        .replace("\u2018", "'").replace("\u2019", "'") 
        .replace("\u201c", '"').replace("\u201d", '"')  
        .replace("\u2026", "...")
        .replace("\u00a0", " ") 
    )
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"`([^`]+?)`", r"<font face='Courier'>\1</font>", text)
    return text

def _normalize_citations(text: str) -> str:
    """Convert [paper_id=1,5] or [1,5] into [1][5]."""
    def repl(m):
        ids = [n.strip() for n in m.group(1).split(",")]
        return "".join(f"[{n}]" for n in ids)
    return CITATION_GROUP_RE.sub(repl, text)


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
        name="H1", parent=styles["Heading1"], fontSize=15, spaceBefore=16, spaceAfter=8,
        textColor=colors.HexColor("#1a1a2e"),
    ))
    styles.add(ParagraphStyle(
        name="H2", parent=styles["Heading2"], fontSize=13, spaceBefore=14, spaceAfter=6,
        textColor=colors.HexColor("#1a1a2e"),
    ))
    styles.add(ParagraphStyle(
        name="H3", parent=styles["Heading3"], fontSize=11.5, spaceBefore=12, spaceAfter=5,
        textColor=colors.HexColor("#1a1a2e"),
    ))
    styles.add(ParagraphStyle(
        name="ReportTitle", parent=styles["Title"], fontSize=18, spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        name="BulletBody", parent=styles["BodyText"],
        fontSize=10.5, leading=14.5, spaceAfter=3,
    ))
    styles.add(ParagraphStyle(
        name="RefEntry", parent=styles["BodyText"],
        fontSize=9, leading=13, leftIndent=18, firstLineIndent=-18, spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        name="TableCell", parent=styles["BodyText"], fontSize=9, leading=12,
    ))
    styles.add(ParagraphStyle(
        name="TableHeader", parent=styles["BodyText"], fontSize=9.5, leading=12,
        textColor=colors.white, fontName="Helvetica-Bold",
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
        name="H1", parent=styles["Heading1"], fontName=serif_bold, fontSize=14,
        spaceBefore=18, spaceAfter=8,
    ))
    styles.add(ParagraphStyle(
        name="H2", parent=styles["Heading2"], fontName=serif_bold, fontSize=12,
        spaceBefore=16, spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        name="H3", parent=styles["Heading3"], fontName=serif_bold, fontSize=11,
        spaceBefore=12, spaceAfter=5,
    ))
    styles.add(ParagraphStyle(
        name="ReportTitle", parent=styles["Title"], fontName=serif_bold,
        fontSize=16, spaceAfter=4, alignment=TA_CENTER,
    ))
    styles.add(ParagraphStyle(
        name="Abstract", parent=styles["BodyText"], fontName=serif,
        fontSize=9.5, leading=13, alignment=TA_JUSTIFY,
        leftIndent=30, rightIndent=30, spaceAfter=16,
    ))
    styles.add(ParagraphStyle(
        name="BulletBody", parent=styles["BodyText"], fontName=serif,
        fontSize=10.5, leading=14.5, spaceAfter=3,
    ))
    styles.add(ParagraphStyle(
        name="RefEntry", parent=styles["BodyText"], fontName=serif,
        fontSize=9, leading=13, leftIndent=18, firstLineIndent=-18, spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        name="TableCell", parent=styles["BodyText"], fontName=serif, fontSize=9, leading=12,
    ))
    styles.add(ParagraphStyle(
        name="TableHeader", parent=styles["BodyText"], fontName=serif_bold, fontSize=9.5,
        leading=12, textColor=colors.white,
    ))
    return styles


def _make_table(rows: list[list[str]], styles) -> Table:
    header, *body_rows = rows
    data = [[Paragraph(_inline_markdown(c.strip()), styles["TableHeader"]) for c in header]]
    for r in body_rows:
        data.append([Paragraph(_inline_markdown(c.strip()), styles["TableCell"]) for c in r])

    table = Table(data, hAlign="LEFT", repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#bbbbbb")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f4f8")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def _flush_bullets(buffer: list[str], flowables: list, styles, ordered: bool):
    if not buffer:
        return
    items = [
        ListItem(Paragraph(_inline_markdown(b), styles["BulletBody"]), spaceAfter=2)
        for b in buffer
    ]
    flowables.append(ListFlowable(
        items,
        bulletType="1" if ordered else "bullet",
        start="1" if ordered else "•",
        leftIndent=16,
        bulletFontSize=9.5,
        spaceBefore=2,
        spaceAfter=8,
    ))
    buffer.clear()


def _parse_table_block(lines: list[str], start_idx: int) -> tuple[list[list[str]], int]:
    """Given lines starting at a '|...|' row, consume the markdown table and
    return (rows, next_index_after_table)."""
    rows = []
    i = start_idx
    header_cells = [c for c in lines[i].strip().strip("|").split("|")]
    rows.append(header_cells)
    i += 1
    if i < len(lines) and TABLE_SEP_RE.match(lines[i]):
        i += 1
    while i < len(lines) and TABLE_ROW_RE.match(lines[i]):
        cells = [c for c in lines[i].strip().strip("|").split("|")]
        rows.append(cells)
        i += 1
    return rows, i


def _flowables_from_body(body: str, styles) -> list:
    """Parse the answer body into headings, bullet lists, tables, and paragraphs."""
    flowables = []
    lines = body.split("\n")
    bullet_buffer: list[str] = []
    ordered_buffer = False
    para_buffer: list[str] = []

    def flush_para():
        if para_buffer:
            text = " ".join(l.strip() for l in para_buffer if l.strip())
            if text:
                flowables.append(Paragraph(_inline_markdown(text), styles["BodyJustified"]))
            para_buffer.clear()

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            flush_para()
            _flush_bullets(bullet_buffer, flowables, styles, ordered_buffer)
            i += 1
            continue

        heading_match = HEADING_RE.match(stripped)
        if heading_match:
            flush_para()
            _flush_bullets(bullet_buffer, flowables, styles, ordered_buffer)
            level = len(heading_match.group(1))
            text = _inline_markdown(heading_match.group(2).strip())
            style_name = {1: "H1", 2: "H2"}.get(level, "H3")
            flowables.append(Paragraph(text, styles[style_name]))
            i += 1
            continue

        if TABLE_ROW_RE.match(stripped):
            flush_para()
            _flush_bullets(bullet_buffer, flowables, styles, ordered_buffer)
            table_rows, next_i = _parse_table_block(lines, i)
            if len(table_rows) >= 2:
                flowables.append(Spacer(1, 4))
                flowables.append(_make_table(table_rows, styles))
                flowables.append(Spacer(1, 10))
            i = next_i
            continue

        bullet_match = BULLET_RE.match(line)
        num_match = NUM_BULLET_RE.match(line)
        if bullet_match or num_match:
            flush_para()
            is_ordered = bool(num_match)
            if bullet_buffer and ordered_buffer != is_ordered:
                _flush_bullets(bullet_buffer, flowables, styles, ordered_buffer)
            ordered_buffer = is_ordered
            bullet_buffer.append((bullet_match or num_match).group(1).strip())
            i += 1
            continue

        cleaned = stripped.replace("**", "")
        if stripped.startswith("**") and stripped.endswith("**") and len(cleaned) < 100:
            flush_para()
            _flush_bullets(bullet_buffer, flowables, styles, ordered_buffer)
            flowables.append(Paragraph(_inline_markdown(cleaned), styles["H3"]))
            i += 1
            continue

        para_buffer.append(line)
        i += 1

    flush_para()
    _flush_bullets(bullet_buffer, flowables, styles, ordered_buffer)
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
    body = _normalize_citations(body)
    title = req.title or "Research Assistant - Answer"

    story = [Paragraph(title, styles["ReportTitle"])]

    if latex_style:
        story.append(Spacer(1, 6))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#333333")))
        story.append(Spacer(1, 10))
        first_para = next((p.strip() for p in body.split("\n\n") if p.strip()), "")
        if first_para and not HEADING_RE.match(first_para):
            story.append(Paragraph("<b>Abstract.</b> " + _inline_markdown(first_para), styles["Abstract"]))
    else:
        story.append(Spacer(1, 4))
        story.append(HRFlowable(width="100%", thickness=0.75, color=colors.HexColor("#1a1a2e")))
        story.append(Spacer(1, 10))

    story.extend(_flowables_from_body(body, styles))

    references = req.references
    ref_flowables = []
    if references:
        ref_flowables.append(Paragraph("References", styles["H2"]))
        for r in references:
            authors = ", ".join(r.authors[:4]) if r.authors else ""
            year = f" ({r.published})" if r.published else ""
            author_part = f"{authors}{year}. " if authors else ""
            entry = f"[{r.id}] {author_part}{_inline_markdown(r.title)}. {r.link}"
            ref_flowables.append(Paragraph(entry, styles["RefEntry"]))
    elif inline_refs:
        ref_flowables.append(Paragraph("References", styles["H2"]))
        for line in inline_refs.split("\n"):
            line = line.strip()
            if line:
                ref_flowables.append(Paragraph(_inline_markdown(line), styles["RefEntry"]))

    if ref_flowables:
        story.append(Spacer(1, 16))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#888888")))
        story.append(Spacer(1, 8))
        story.extend(ref_flowables)

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