"""
pdf_renderer.py

Replaces the old ReportLab flowable-based PDF pipeline entirely.

Why: ReportLab has no math typesetting engine. The old approach
(_latex_to_ascii in the previous export.py) hand-transliterated LaTeX
commands into plain ASCII approximations via string substitution
(\\frac{a}{b} -> "(a)/(b)", \\sqrt{x} -> "sqrt(x)", etc). That's fundamentally
a dead end: any LaTeX command not in the hardcoded map (\\Bigl, \\top, \\dots,
\\sin, \\cos, ...) leaked through as raw, broken text in the exported PDF,
even when the same markdown rendered perfectly via KaTeX in the chat UI.

New approach: the SAME markdown the chat renders (via react-markdown +
remark-math + rehype-katex) is converted to HTML server-side (via Python's
`markdown` library, GFM-style tables/fenced-code extensions), leaving
$...$ / $$...$$ delimiters untouched. That HTML is loaded into a headless
Chromium (Playwright) alongside a vendored MathJax bundle, which typesets
the math for real (actual glyphs, actual fraction bars, actual sqrt
radicals) before printing to PDF. Chat and PDF now share one source of
truth for both markdown structure AND math, instead of two independently
maintained parsers drifting apart.
"""
import base64
import os
import re

import markdown as md_lib
from playwright.sync_api import sync_playwright

from app.pdf.pdf_template import build_pdf_html

EXPORT_DIR = "exports"
os.makedirs(EXPORT_DIR, exist_ok=True)

CITATION_GROUP_RE = re.compile(r"\[(?:paper_id\s*=\s*)?(\d+(?:\s*,\s*\d+)*)\]")
# Matches markdown images pointing at our own /exports/ static mount, e.g.
# ![Chart title](/exports/chart-abcd1234.png)
IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(/?exports/([^)]+)\)")


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
            return body, parts[1].strip() or None
    return answer, None


def _image_to_data_uri(rel_path: str) -> str | None:
    """Embed chart images as base64 data URIs rather than file:// or http://
    references, so Playwright never needs filesystem/network access to
    resolve them at PDF-print time — the HTML is fully self-contained."""
    abs_path = os.path.join(EXPORT_DIR, rel_path)
    if not os.path.isfile(abs_path):
        print(f"[pdf_renderer] chart image not found, skipping: {abs_path}")
        return None
    ext = os.path.splitext(abs_path)[1].lstrip(".").lower() or "png"
    mime = "jpeg" if ext in ("jpg", "jpeg") else ext
    with open(abs_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:image/{mime};base64,{b64}"


def _preprocess_images(body: str) -> str:
    """Rewrite ![alt](/exports/x.png) markdown images to use inline base64
    data URIs, and wrap in a <figure> via a raw-HTML passthrough marker
    (markdown's default img rendering doesn't add a caption, so we handle
    figure/figcaption manually post-conversion via a placeholder)."""
    def repl(m):
        alt, rel_path = m.group(1), m.group(2)
        data_uri = _image_to_data_uri(rel_path)
        if data_uri is None:
            return ""  # drop broken image references rather than show a broken-image icon
        caption = f"<figcaption>{alt}</figcaption>" if alt else ""
        return f'\n\n<figure><img src="{data_uri}" alt="{alt}">{caption}</figure>\n\n'

    return IMAGE_RE.sub(repl, body)


def markdown_to_html(body: str) -> str:
    """Convert answer markdown to HTML, preserving $...$/$$...$$ math
    delimiters untouched for MathJax to process client-side. GFM tables and
    fenced code blocks are handled by python-markdown's extensions, matching
    what react-markdown + remark-gfm does in the chat UI."""
    body = _preprocess_images(body)
    html = md_lib.markdown(
        body,
        extensions=["tables", "fenced_code", "nl2br", "sane_lists"],
        output_format="html5",
    )
    return html


def _build_references_html(references: list[dict] | None, inline_refs: str | None) -> str:
    if references:
        entries = []
        for r in references:
            authors = ", ".join((r.get("authors") or [])[:4])
            year = f" ({r['published']})" if r.get("published") else ""
            author_part = f"{authors}{year}. " if authors else ""
            title = r.get("title", "")
            link = r.get("link", "")
            entries.append(
                f'<div class="ref-entry">[{r["id"]}] {author_part}{title}. '
                f'<a href="{link}">{link}</a></div>'
            )
        return '<div class="references"><h2>References</h2>' + "".join(entries) + "</div>"

    if inline_refs:
        lines = [l.strip() for l in inline_refs.split("\n") if l.strip() and not IMAGE_RE.match(l.strip())]
        entries = "".join(f'<div class="ref-entry">{l}</div>' for l in lines)
        return '<div class="references"><h2>References</h2>' + entries + "</div>"

    return ""


def render_answer_pdf(
    answer: str,
    title: str,
    references: list[dict] | None = None,
    chart_path: str | None = None,
    latex_style: bool = False,
) -> bytes:
    """Main entry point: answer markdown -> themed PDF bytes."""
    body, inline_refs = _split_answer_and_references(answer)
    body = _normalize_citations(body)

    # If chart_path was passed explicitly and wasn't already embedded via an
    # inline ![]() image in the answer body, append it at the end.
    if chart_path and not IMAGE_RE.search(body):
        rel = os.path.basename(chart_path)
        body += f"\n\n![]({'/' + EXPORT_DIR + '/' + rel})\n"

    body_html = markdown_to_html(body)

    if latex_style:
        # Pull the first paragraph out as an "Abstract" block, matching the
        # existing Academic PDF export style.
        first_para_match = re.search(r"<p>(.*?)</p>", body_html, re.DOTALL)
        if first_para_match:
            abstract_html = f'<div class="abstract"><strong>Abstract.</strong> {first_para_match.group(1)}</div>'
            body_html = abstract_html + body_html[first_para_match.end():]

    refs_html = _build_references_html(references, inline_refs)
    full_body_html = body_html + refs_html

    html_doc = build_pdf_html(full_body_html, title=title, latex_style=latex_style)

    return _print_html_to_pdf(html_doc)


def _print_html_to_pdf(html_doc: str) -> bytes:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(html_doc, wait_until="load")
            # Wait for MathJax to finish typesetting before printing. MathJax
            # startup.typeset is false (see pdf_template.py config), so we
            # explicitly trigger + await MathJax.typesetPromise() here.
            page.evaluate(
                """
                async () => {
                    if (window.MathJax && window.MathJax.typesetPromise) {
                        await window.MathJax.typesetPromise();
                    }
                }
                """
            )
            pdf_bytes = page.pdf(
                format="Letter",
                print_background=True,
                margin={"top": "0.9in", "bottom": "0.9in", "left": "0.85in", "right": "0.85in"},
            )
            return pdf_bytes
        finally:
            browser.close()