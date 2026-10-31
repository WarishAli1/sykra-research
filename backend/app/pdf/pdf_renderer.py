"""
pdf_renderer.py
Answer markdown -> HTML -> headless Chromium (Playwright) + vendored MathJax
-> PDF. Math spans are stashed into control-char tokens BEFORE python-markdown
runs and restored AFTER, so markdown can never corrupt LaTeX.
"""
import base64
import html as html_lib
import os
import re
from html.parser import HTMLParser
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


_ALLOWED_TAGS = {
    "p", "br", "strong", "b", "em", "i", "u", "s", "span", "ul", "ol", "li",
    "h1", "h2", "h3", "h4", "h5", "h6", "table", "thead", "tbody", "tr", "th", "td",
    "blockquote", "code", "pre", "hr", "sup", "sub", "a",
}
_VOID_TAGS = {"br", "hr"}
_DROP_CONTENT = {"script", "style", "iframe", "object", "embed", "noscript", "template", "svg", "math"}
_STYLE_TAGS = {"p", "span", "li", "th", "td", "h1", "h2", "h3", "h4", "h5", "h6"}
_STYLE_RULES = {
    "font-family": re.compile(r"^[\w\s,'\"-]{1,80}$"),
    "font-size": re.compile(r"^\d{1,3}(\.\d+)?(pt|px|em|%)$"),
    "line-height": re.compile(r"^\d{1,2}(\.\d+)?(pt|px|em|%)?$"),
    "font-weight": re.compile(r"^(normal|bold|[1-9]00)$"),
    "text-align": re.compile(r"^(left|right|center|justify)$"),
    "text-decoration": re.compile(r"^(none|underline|line-through)$"),
    "color": re.compile(r"^(#[0-9a-fA-F]{3,8}|[a-zA-Z]{3,20})$"),
}


def _clean_style(value: str) -> str:
    out = []
    for decl in (value or "").split(";"):
        if ":" not in decl:
            continue
        k, v = decl.split(":", 1)
        k, v = k.strip().lower(), v.strip()
        rule = _STYLE_RULES.get(k)
        if rule and rule.match(v):
            out.append(f"{k}:{v}")
    return ";".join(out)


class _Sanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.stack: list[str] = []
        self.skip = 0

    @staticmethod
    def _attrs(tag, attrs):
        d = {(k or "").lower(): (v or "") for k, v in attrs}
        parts = []
        if tag in _STYLE_TAGS:
            st = _clean_style(d.get("style", ""))
            if st:
                parts.append(f'style="{html_lib.escape(st, quote=True)}"')
        if tag in ("td", "th"):
            for k in ("colspan", "rowspan"):
                if re.fullmatch(r"[0-9]{1,2}", d.get(k, "")):
                    parts.append(f'{k}="{d[k]}"')
        if tag == "a":
            href = d.get("href", "").strip()
            if re.match(r"^(https?://|mailto:|#)", href, re.I):
                parts.append(f'href="{html_lib.escape(href, quote=True)}" target="_blank" rel="noopener noreferrer"')
        return (" " + " ".join(parts)) if parts else ""

    def handle_starttag(self, tag, attrs):
        if self.skip:
            if tag in _DROP_CONTENT:
                self.skip += 1
            return
        if tag in _DROP_CONTENT:
            self.skip = 1
            return
        if tag not in _ALLOWED_TAGS:
            return
        self.out.append(f"<{tag}{self._attrs(tag, attrs)}>")
        if tag not in _VOID_TAGS:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        if tag in _DROP_CONTENT:
            return
        self.handle_starttag(tag, attrs)
        if tag in _ALLOWED_TAGS and tag not in _VOID_TAGS and not self.skip:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.skip:
            if tag in _DROP_CONTENT:
                self.skip -= 1
            return
        if tag in _VOID_TAGS or tag not in self.stack:
            return
        while self.stack:
            t = self.stack.pop()
            self.out.append(f"</{t}>")
            if t == tag:
                break

    def handle_data(self, data):
        if not self.skip:
            self.out.append(html_lib.escape(data, quote=False))


def sanitize_report_html(raw: str | None) -> str:
    """Allow-list sanitizer: safe tags, a handful of typographic style properties, nothing else."""
    if not raw:
        return ""
    p = _Sanitizer()
    p.feed(raw)
    p.close()
    while p.stack:
        p.out.append(f"</{p.stack.pop()}>")
    return "".join(p.out)


_P_WRAP = re.compile(r"^\s*<p([^>]*)>(.*)</p>\s*$", re.S)


def _heading_html(title_html: str | None, title: str, tag: str, extra_attrs: str = "") -> str:
    """Single-paragraph editor html -> <h1>/<h2> carrying the same inline formatting."""
    clean = sanitize_report_html(title_html)
    m = _P_WRAP.match(clean) if clean else None
    if m:
        return f"<{tag}{extra_attrs}{m.group(1)}>{m.group(2)}</{tag}>"
    return f"<{tag}{extra_attrs}>{html_lib.escape(title or '')}</{tag}>"


def _sections_body_html(sections: list[dict]) -> str:
    parts = []
    for s in sections:
        head = _heading_html(s.get("title_html"), s.get("title") or "", "h2")
        if s.get("html"):
            body = _normalize_citations(sanitize_report_html(s["html"]))
        else:
            md = _normalize_citations(_strip_disclaimer(s.get("markdown") or ""))
            body = markdown_to_html(sanitize_for_web(md))
        parts.append(f"<section>{head}{body}</section>")
    return "".join(parts)


def render_answer_pdf(
    answer: str,
    title: str,
    references: list[dict] | None = None,
    chart_path: str | None = None,
    latex_style: bool = False,
    sections: list[dict] | None = None,
    title_html: str | None = None,
) -> bytes:
    """Main entry point: answer markdown -> branded PDF bytes.

    When `sections` is given, each section is rendered from its stored formatted
    html (falling back to markdown), and the title / headings keep their own formatting.
    """
    if sections:
        nice_title = (title or "").strip() or "Research Report"
        body_html = _sections_body_html(sections)
        refs_html = _build_references_html(references, None)
        title_block = _heading_html(title_html, nice_title, "h1", ' class="report-title"')
        html_doc = build_pdf_html(body_html + refs_html, title=nice_title, latex_style=latex_style,
                                  title_block=title_block, exact_title=True)
        return _print_html_to_pdf(html_doc, nice_title)
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