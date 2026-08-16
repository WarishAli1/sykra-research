"""
pdf_renderer.py
Answer markdown -> HTML -> headless Chromium (Playwright) + vendored MathJax
-> PDF. Math spans are stashed into control-char tokens BEFORE python-markdown
runs and restored AFTER, so markdown can never corrupt LaTeX.
"""
import base64
import os
import re
import markdown as md_lib
from playwright.sync_api import sync_playwright
from app.utils.text_sanitizer import sanitize_for_web
from app.pdf.pdf_template import (
    build_pdf_html,
    letterhead_header_template,
    letterhead_footer_template,
    prettify_title,
)

EXPORT_DIR = "exports"
os.makedirs(EXPORT_DIR, exist_ok=True)

CITATION_GROUP_RE = re.compile(
    r"\[(?:paper_id\s*=\s*)?(\d+(?:\s*,\s*(?:paper_id\s*=\s*)?\d+)*)\]"
)
IMAGE_RE = re.compile(r"!\[([^\]]*)\]\((/?exports/[^)]+)\)")
REF_MARKER = "\n\n---\n\nReferences"

DISCLAIMER_RE = re.compile(
    r"\n*\s*\*?_?Sykra can make mistakes\.[^\n]*?starting baseline\.?_?\*?\s*"
    r"(?=\n*(?:---\s*\n*)?(?:#{1,6}\s*)?References\b|$)",
    re.IGNORECASE,
)


def _strip_disclaimer(text: str) -> str:
    return DISCLAIMER_RE.sub("\n\n", text)


def _normalize_citations(text: str) -> str:
    """Convert [paper_id=1,5] / [1,5] into [1][5]."""
    def repl(m):
        ids = [
            re.sub(r"^paper_id\s*=\s*", "", n.strip())
            for n in m.group(1).split(",")
        ]
        return "".join(f"[{n}]" for n in ids if n.isdigit())
    return CITATION_GROUP_RE.sub(repl, text)


def _split_answer_and_references(answer: str) -> tuple[str, str | None]:
    if REF_MARKER in answer:
        body, refs = answer.split(REF_MARKER, 1)
        return body.strip(), refs.strip() or None
    if "References" in answer:
        body, refs = answer.split("References", 1)
        return body.strip(), refs.strip() or None
    return answer, None


def _image_to_data_uri(rel_path: str) -> str | None:
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
    def repl(m):
        alt, path = m.group(1), m.group(2)
        rel_path = path.lstrip("/")
        if rel_path.startswith("exports/"):
            rel_path = rel_path[len("exports/"):]
        data_uri = _image_to_data_uri(rel_path)
        if data_uri is None:
            return ""
        caption = f"<figcaption>{alt}</figcaption>" if alt else ""
        return f'\n\n<figure><img src="{data_uri}" alt="{alt}">{caption}</figure>\n\n'
    return IMAGE_RE.sub(repl, body)


def markdown_to_html(body: str) -> str:
    body = _preprocess_images(body)
    stash: list[str] = []
    OPEN, CLOSE = "zZMATHSTASHz", "zENDSTASHZz"

    def _stash(m: re.Match) -> str:
        stash.append(m.group(0))
        return f"{OPEN}{len(stash) - 1}{CLOSE}"

    protected = re.sub(r"\$\$.*?\$\$", _stash, body, flags=re.DOTALL)
    protected = re.sub(r"\$[^$\n]+?\$", _stash, protected)
    html = md_lib.markdown(
        protected,
        extensions=["tables", "fenced_code", "nl2br", "sane_lists"],
        output_format="html5",
    )
    restore_re = re.compile(re.escape(OPEN) + r"(\d+)" + re.escape(CLOSE))
    return restore_re.sub(lambda m: stash[int(m.group(1))], html)


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
        lines = [
            l.strip()
            for l in inline_refs.split("\n")
            if l.strip() and not IMAGE_RE.match(l.strip())
        ]
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
    """Main entry point: answer markdown -> branded PDF bytes."""
    answer = _strip_disclaimer(answer)
    body, inline_refs = _split_answer_and_references(answer)
    body = _normalize_citations(body)
    body = sanitize_for_web(body)
    if chart_path and not IMAGE_RE.search(body):
        rel = os.path.basename(chart_path)
        body += f"\n\n![Chart](/exports/{rel})\n"

    body_html = markdown_to_html(body)
    if latex_style:
        first_para_match = re.search(r"<p>(.*?)</p>", body_html, re.DOTALL)
        if first_para_match:
            abstract_html = (
                f'<div class="abstract"><strong>Abstract. </strong>'
                f'{first_para_match.group(1)}</div>'
            )
            body_html = abstract_html + body_html[first_para_match.end():]

    refs_html = _build_references_html(references, inline_refs)
    nice_title = prettify_title(title, source=answer)
    html_doc = build_pdf_html(body_html + refs_html, title=title, latex_style=latex_style)
    return _print_html_to_pdf(html_doc, nice_title)


def _print_html_to_pdf(html_doc: str, nice_title: str) -> bytes:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(html_doc, wait_until="load")
            page.evaluate(
                """
                async () => {
                    if (window.MathJax) {
                        if (window.MathJax.startup && window.MathJax.startup.promise) {
                            await window.MathJax.startup.promise;
                        }
                        if (window.MathJax.typesetPromise) {
                            await window.MathJax.typesetPromise();
                        }
                    }
                }
                """
            )
            page.wait_for_timeout(300)
            return page.pdf(
                format="Letter",
                print_background=True,
                display_header_footer=True,
                margin={"top": "1.05in", "bottom": "0.95in",
                        "left": "0.85in", "right": "0.85in"},
                header_template=letterhead_header_template(),
                footer_template=letterhead_footer_template(nice_title),
            )
        finally:
            browser.close()