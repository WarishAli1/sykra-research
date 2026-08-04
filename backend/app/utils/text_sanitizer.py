import re
import unicodedata
from typing import Callable

_CURRENCY_RE = re.compile(r'\$(\d[\d,.]*)(?!\$)')

def fix_currency(text: str) -> str:
    """Replace $<number> with USD <number>. Does NOT touch $x$ math."""
    return _CURRENCY_RE.sub(r'USD \1', text)

_CITATION_MARKER_RE = re.compile(
    r'[\[【]\s*paper_id\s*[=＝]\s*\d+\s*[\]】]',
    re.IGNORECASE,
)

def strip_stray_citations(text: str) -> str:
    """Remove any [paper_id=N] or 【paper_id=N】 that survived rewriting."""
    return _CITATION_MARKER_RE.sub('', text)

_FULLWIDTH_MAP = str.maketrans({
    '【': '[', '】': ']',
    '（': '(', '）': ')',
    '：': ':', '；': ';',
    '，': ',', '＝': '=',
    '！': '!', '？': '?',
    '｛': '{', '｝': '}',
    '［': '[', '］': ']',
})

def normalize_fullwidth(text: str) -> str:
    """Convert fullwidth CJK punctuation to ASCII equivalents."""
    return text.translate(_FULLWIDTH_MAP)

_LITERAL_ESCAPE_RE = re.compile(r'\\[nt](?![a-zA-Z])')
_DOUBLE_BACKSLASH_RE = re.compile(r'\\(?![a-zA-Z\[({\\])')

def fix_orphaned_backslashes(text: str) -> str:
    """Remove literal \\n, \\t, and stray \\\\ outside math blocks."""
    parts = re.split(r'(\$\$.*?\$\$|\$[^$\n]+?\$)', text, flags=re.DOTALL)
    result = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            result.append(part)
        else:
            part = _LITERAL_ESCAPE_RE.sub('', part)
            part = _DOUBLE_BACKSLASH_RE.sub('', part)
            result.append(part)
    return ''.join(result)

_DASH_CHARS = re.compile(
    "[\u2010\u2011\u2012\u2013\u2014\u2015\u2212\u00AD\u207B\u208B]"
)
_UNICODE_MAP = str.maketrans({
    '\u2018': "'",
    '\u2019': "'",
    '\u201c': '"',
    '\u201d': '"',
    '\u00a0': ' ',
    '\u200b': '',
    '\ufeff': '',
})

def normalize_dashes(text: str) -> str:
    """Convert all Unicode dash variants to ASCII hyphen."""
    return _DASH_CHARS.sub("-", text)

def normalize_unicode(text: str) -> str:
    """Normalize smart quotes, NBSP, zero-width chars, AND dashes."""
    text = text.translate(_UNICODE_MAP)
    text = _DASH_CHARS.sub("-", text)
    return text

_BRACKET_MATH_BLOCK_RE = re.compile(
    r"^[ \t]*\[[ \t]*\n(.*?)\n[ \t]*\][ \t]*$",
    re.DOTALL | re.MULTILINE,
)
_BRACKET_MATH_LINE_RE = re.compile(
    r"^[ \t]*\[(.+?)\][ \t]*$",
    re.MULTILINE,
)
_LATEX_CONTENT_RE = re.compile(r"\\[a-zA-Z]{2,}|\\top|\\in\b|_\{|\^\{")

def _looks_like_latex(inner: str) -> bool:
    """True if `inner` contains recognizable LaTeX commands/markup, as
    opposed to ordinary prose or a citation/link label."""
    return bool(_LATEX_CONTENT_RE.search(inner))

def fix_bracket_display_math(text: str) -> str:
    """Convert bare `[ ...latex... ]` blocks (own-line, single- or
    multi-line) into proper `$$...$$` display math."""
    def block_repl(m: re.Match) -> str:
        inner = m.group(1)
        if _looks_like_latex(inner):
            return "$$\n" + inner.strip() + "\n$$"
        return m.group(0)
    text = _BRACKET_MATH_BLOCK_RE.sub(block_repl, text)

    def line_repl(m: re.Match) -> str:
        inner = m.group(1)
        if _looks_like_latex(inner):
            return "$$" + inner.strip() + "$$"
        return m.group(0)
    text = _BRACKET_MATH_LINE_RE.sub(line_repl, text)
    return text

_FENCE_RE = re.compile(r"^[ \t]*\$\$[ \t]*$")
_PROSE_BOUNDARY_RE = re.compile(r"(?:^[ \t]*$)|(?:^[ \t]*#{1,6}\s)")

def normalize_math_fences(md: str) -> str:
    """Ensure $$ delimiters are on their own lines and properly paired."""
    s = md
    for _ in range(2):
        s = re.sub(r"([^\n])\$\$", r"\1\n$$", s)   # text$$  → text\n$$
        s = re.sub(r"\$\$([^\n])", r"$$\n\1", s)   # $$text  → $$\ntext
        s = re.sub(r"\n{3,}", "\n\n", s)
    lines, out, in_math = s.split("\n"), [], False

    def ensure_blank():
        if out and out[-1].strip() != "":
            out.append("")

    i = 0
    while i < len(lines):
        line = lines[i]
        if _FENCE_RE.match(line):
            if not in_math:
                if i + 1 < len(lines) and _FENCE_RE.match(lines[i + 1]):
                    i += 2
                    continue
                ensure_blank()
                out.append("$$")
                in_math = True
            else:
                out.append("$$")
                in_math = False
                ensure_blank()
        elif in_math and _PROSE_BOUNDARY_RE.match(line):
            out.append("$$")
            in_math = False
            out.append(line)
            if line.strip() != "":
                ensure_blank()
        else:
            out.append(line)
        i += 1
    if in_math:
        out.append("$$")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out))

def collapse_whitespace(text: str) -> str:
    """Collapse 3+ newlines to 2, strip trailing spaces per line."""
    lines = [line.rstrip() for line in text.split('\n')]
    text = '\n'.join(lines)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def sanitize_abstract(text: str, max_chars: int = 300) -> str:
    """Clean a paper abstract for display. Strips notation, control chars."""
    if not text:
        return "No abstract available."
    text = text[:max_chars].strip()
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')
    text = re.sub(r'(?<=\s)[A-Z](?=\s)', '', text)
    text = re.sub(r'\b\d+(?:\.\d+)+\s*', '', text)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    if len(text) < 25:
        return "[Abstract contains mostly mathematical notation]"
    return text

WEB_PIPELINE: list[Callable[[str], str]] = [
    fix_currency,
    normalize_fullwidth,
    strip_stray_citations,
    fix_orphaned_backslashes,
    normalize_unicode,
    fix_bracket_display_math,
    normalize_math_fences,
    collapse_whitespace,
]

def sanitize_for_web(text: str) -> str:
    """
    Apply the full web sanitization pipeline. Idempotent.
    Used for BOTH web rendering (KaTeX) AND PDF export
    (Playwright + MathJax), because the PDF pipeline is HTML-based.
    """
    if not text:
        return ""
    for rule in WEB_PIPELINE:
        text = rule(text)
    return text

sanitize_for_pdf = sanitize_for_web

__all__ = [
    "sanitize_for_web",
    "sanitize_for_pdf",
    "normalize_math_fences",
    "normalize_dashes",
    "normalize_unicode",
    "normalize_fullwidth",
    "fix_currency",
    "fix_orphaned_backslashes",
    "collapse_whitespace",
    "strip_stray_citations",
    "sanitize_abstract",
    "fix_bracket_display_math",
]