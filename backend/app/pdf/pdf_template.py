"""
pdf_template.py — Sykra Research report design system.
Letterhead: segmented accent bar on top, logo lockup left, date right,
thin rule + sage accent, mirrored accent bar in the footer,
and a faint watermark behind every page.
Brand palette (60/30/10):
  60%  paper / mint-white : page canvas, tints, zebra rows
  30%  deep pine          : letterhead, headings, table headers, ink
  10%  sage + mint        : rules, overlines, markers, accents
"""
import base64
import html as html_lib
import os
import re
import struct
from collections import Counter
from datetime import datetime
from functools import lru_cache

from app.config import settings

BRAND_NAME = "Sykra Research"
WATERMARK_ENABLED = True  

_THEME = {
    "pine950": "#051F20",
    "pine900": "#0B2B26",
    "pine800": "#163832",
    "pine700": "#235347",
    "sage":    "#8EB69B",
    "mint":    "#DAF1DE",
    "mintsoft": "#F0F8F3",
    "paper":   "#FBFDFC",
    "ink":     "#1C2624",
    "inksoft": "#5C6B66",
    "line":    "#D9E8DF",
}

_MATHJAX_CONFIG = r"""
<script>
window.MathJax = {
  tex: {
    inlineMath: [["$", "$"], ["\\(", "\\)"]],
    displayMath: [["$$", "$$"], ["\\[", "\\]"]],
    processEscapes: true
  },
  svg: { fontCache: "global" },
  options: { enableMenu: false }
};
</script>
"""

_CSS = """
  * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  body { font-family: __FONT__; color: #1C2624; background: #FBFDFC;
         font-size: 11pt; line-height: 1.6; orphans: 3; widows: 3; }

  /* faint watermark repeated on every printed page */
  .watermark { position: fixed; top: 42%; left: 50%;
               transform: translate(-50%, -50%);
               z-index: -1; opacity: 0.05; pointer-events: none; }

  /* ── report title block (first page) ───────────────────────────── */
  .report-header { margin: 0 0 16pt; padding: 0 0 10pt; position: relative;
                   border-bottom: 2.5pt solid #163832; }
  .report-header::after { content: ""; position: absolute; left: 0; right: 0;
                          bottom: -5.5pt; height: 1pt; background: #8EB69B; }
  .report-overline { font-size: 8.5pt; font-weight: 700; letter-spacing: .24em;
                     text-transform: uppercase; color: #235347; margin: 0 0 7pt; }
  h1.report-title { font-size: 20pt; line-height: 1.22; margin: 0 0 6pt;
                    color: #051F20; font-weight: 700; letter-spacing: -0.2pt; }
  .report-meta { font-size: 9pt; color: #5C6B66; margin: 0; }
  .report-meta .sep { color: #8EB69B; margin: 0 5pt; }

  /* ── typography ────────────────────────────────────────────────── */
  h1, h2, h3, h4 { font-family: __FONT__; color: #0B2B26; line-height: 1.25;
                   break-inside: avoid; break-after: avoid-page; }
  h1 { font-size: 18pt; margin: 16pt 0 8pt; }
  h2 { font-size: 14pt; margin: 16pt 0 8pt; padding-bottom: 4pt;
       border-bottom: 1pt solid #D9E8DF; }
  h3 { font-size: 12pt; color: #163832; margin: 12pt 0 6pt; }
  h4 { font-size: 11pt; color: #235347; margin: 10pt 0 4pt; }
  p { margin: 0 0 8pt; }
  a { color: #235347; }
  ul, ol { margin: 0 0 8pt; padding-left: 18pt; }
  li { margin-bottom: 3pt; }
  li::marker { color: #235347; }
  hr { border: 0; border-top: 1pt solid #8EB69B; margin: 14pt 0; }

  /* ── tables ────────────────────────────────────────────────────── */
  table { border-collapse: collapse; width: 100%; margin: 10pt 0; font-size: 10pt; }
  thead { display: table-header-group; }
  tr { break-inside: avoid; }
  th, td { border: 1px solid #D9E8DF; padding: 5pt 8pt; text-align: left;
           vertical-align: top; }
  th { background: #0B2B26; color: #EAF5EE; font-weight: 600; border-color: #0B2B26; }
  tbody tr:nth-child(even) { background: #F0F8F3; }

  /* ── figures / code ────────────────────────────────────────────── */
  figure { margin: 12pt 0; text-align: center; break-inside: avoid; }
  figure img { max-width: 100%; border: 1px solid #D9E8DF; border-radius: 4pt; }
  figcaption { font-size: 9pt; color: #5C6B66; margin-top: 5pt; }
  pre { background: #F0F8F3; border: 1px solid #D9E8DF; border-left: 3pt solid #8EB69B;
        padding: 8pt 10pt; font-size: 9pt; white-space: pre-wrap;
        border-radius: 0 3pt 3pt 0; break-inside: avoid; }
  code { font-family: 'SFMono-Regular', Consolas, Menlo, monospace; font-size: 9.5pt;
         background: #F0F8F3; padding: .5pt 3pt; border-radius: 3pt; }
  pre code { background: none; padding: 0; }

  /* ── abstract ──────────────────────────────────────────────────── */
  .abstract { padding: 10pt 14pt; background: #F0F8F3; border-left: 3pt solid #235347;
              margin: 0 0 14pt; font-size: 10.5pt; }

  /* ── references ────────────────────────────────────────────────── */
  .references { margin-top: 18pt; font-size: 9.8pt; }
  .references h2 { border-bottom-color: #8EB69B; }
  .ref-entry { margin-bottom: 6pt; padding-left: 14pt; text-indent: -14pt; }
  .ref-entry a { color: #235347; word-break: break-all; }

  mjx-container { color: #1C2624; }
  mjx-container[display="true"] { margin: 10pt 0 !important; }
"""


def _best_case_variant(word: str, text: str) -> str:
    """Borrow the canonical casing of a word from the source text.
    'cnns' -> 'CNNs', 'shufflenet' -> 'ShuffleNet', 'ai' -> 'AI' —
    detected from how the term actually appears in the answer."""
    already_cased = word[:1].isupper() or sum(c.isupper() for c in word) >= 2
    if not text:
        return word if already_cased else word.capitalize()
    matches = re.findall(rf"\b{re.escape(word)}\b", text, flags=re.IGNORECASE)
    if not matches:
        return word if already_cased else word.capitalize()
    counts = Counter(matches)
    cased = [v for v in counts if sum(c.isupper() for c in v) >= 2]
    if cased:
        return max(cased, key=counts.get)
    return word.capitalize()


def prettify_title(raw: str | None, source: str = "") -> str:
    """'cnns-viable-mobile' + answer text -> 'CNNs Viable Mobile'.
    No dictionaries: casing is learned from the source document itself."""
    base = (raw or "").strip().replace("\\", "/")
    base = os.path.basename(base)
    base = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", base)
    base = re.sub(r"[-_.]+", " ", base)
    base = re.sub(r"\s+", " ", base).strip()
    if not base:
        return "Research Report"
    words = [w for w in base.split(" ") if w]
    return " ".join(_best_case_variant(w, source) for w in words) or "Research Report"


@lru_cache(maxsize=1)
def _logo_asset() -> tuple[str, float] | None:
    """Return (data_uri, aspect_ratio=width/height)."""
    path = settings.LOGO_PATH
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    try:
        if ext == "svg":
            with open(path, "r", encoding="utf-8") as f:
                svg = f.read()
            svg = svg.replace("\r", "").replace("\n", "")
            svg = re.sub(r"\s*=\s*", "=", svg)
            svg = re.sub(r'"\s+', '"', svg)
            svg = re.sub(r'\s+"', '"', svg)
            svg = re.sub(r">\s+<", "><", svg)
            svg = svg.replace('fill="black"', 'fill="#051F20"')
            svg = svg.replace("fill:#000", "fill:#051F20")
            b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
            return "data:image/svg+xml;base64," + b64, 1.0
        with open(path, "rb") as f:
            raw = f.read()
        mime = {"png": "png", "jpg": "jpeg", "jpeg": "jpeg"}.get(ext, "png")
        aspect = 1.0
        if raw[:8] == b"\x89PNG\r\n\x1a\n" and len(raw) > 24:
            w, h = struct.unpack(">II", raw[16:24])
            if h:
                aspect = w / h
        return f"data:image/{mime};base64,{base64.b64encode(raw).decode('ascii')}", aspect
    except OSError:
        print("[pdf_template] logo not found at", path)
        return None


def letterhead_header_template(title: str = "") -> str:
    """Logo lockup left, date right, segmented accent bar on top,
    thin rule + sage accent below. No duplicate wordmark/title text."""
    t = _THEME
    asset = _logo_asset()
    if asset:
        uri, aspect = asset
        h_px = 32
        w_px = max(24, round(h_px * aspect))
        brand = f'<img src="{uri}" style="height:{h_px}px;width:{w_px}px;vertical-align:middle;" />'
    else:
        brand = (f'<span style="font-size:13px;font-weight:700;color:{t["pine950"]};'
                 f'letter-spacing:.2px;">{BRAND_NAME}</span>')
    date_str = datetime.now().strftime("%d %b %Y")
    return (
        '<div style="width:100%;font-family:Inter,\'Segoe UI\',Helvetica,Arial,sans-serif;">'
        '<table style="width:100%;border-collapse:collapse;"><tr>'
        f'<td style="border-top:4px solid {t["pine900"]};"></td>'
        f'<td style="border-top:4px solid {t["pine700"]};width:18%;"></td>'
        f'<td style="border-top:4px solid {t["sage"]};width:7%;"></td>'
        '</tr></table>'
        '<div style="padding:20px 82px 0 82px;">'
        '<table style="width:100%;border-collapse:collapse;"><tr>'
        f'<td style="vertical-align:middle;">{brand}</td>'
        f'<td style="text-align:right;vertical-align:middle;">'
        f'<span style="font-size:8px;font-weight:600;letter-spacing:2.2px;'
        f'text-transform:uppercase;color:{t["pine700"]};">{date_str}</span></td>'
        '</tr></table>'
        f'<div style="border-top:1.5px solid {t["pine800"]};margin-top:10px;"></div>'
        '<table style="width:100%;border-collapse:collapse;"><tr>'
        f'<td style="border-top:3px solid {t["sage"]};width:64px;"></td>'
        '<td style="border-top:3px solid transparent;"></td>'
        '</tr></table>'
        '</div></div>'
    )


def letterhead_footer_template(title: str) -> str:
    t = _THEME
    safe = html_lib.escape(title or "Research Report")
    return (
        '<div style="width:100%;font-family:Inter,\'Segoe UI\',Helvetica,Arial,sans-serif;">'
        '<div style="padding:0 82px 7px 82px;">'
        '<table style="width:100%;border-collapse:collapse;"><tr>'
        f'<td style="font-size:8px;color:{t["inksoft"]};">{safe}'
        f'<span style="color:{t["sage"]};">&nbsp;&nbsp;•&nbsp;&nbsp;</span>{BRAND_NAME}'
        f'<span style="color:{t["sage"]};">&nbsp;&nbsp;•&nbsp;&nbsp;</span>Confidential</td>'
        f'<td style="text-align:right;font-size:8px;color:{t["inksoft"]};">'
        'Page <span class="pageNumber"></span> of <span class="totalPages"></span></td>'
        '</tr></table></div>'
        '<table style="width:100%;border-collapse:collapse;"><tr>'
        f'<td style="border-top:3px solid {t["sage"]};width:7%;"></td>'
        f'<td style="border-top:3px solid {t["pine700"]};width:18%;"></td>'
        f'<td style="border-top:5px solid {t["pine900"]};"></td>'
        '</tr></table>'
        '</div>'
    )


def _mathjax_script_tag() -> str:
    if os.path.isfile(settings.MATHJAX_JS_PATH):
        with open(settings.MATHJAX_JS_PATH, "r", encoding="utf-8") as f:
            js = f.read()
        return _MATHJAX_CONFIG + f"\n<script>{js}</script>"
    return (
        _MATHJAX_CONFIG
        + '\n<script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js"></script>'
    )


def build_pdf_html(body_html: str, title: str, latex_style: bool) -> str:
    nice = prettify_title(title)
    date_str = datetime.now().strftime("%d %B %Y")
    serif_font = "'Source Serif Pro', Georgia, 'Times New Roman', serif"
    sans_font = "'Inter', 'Segoe UI', Helvetica, Arial, sans-serif"
    css = _CSS.replace("__FONT__", serif_font if latex_style else sans_font)
    safe_title = html_lib.escape(nice)

    watermark = ""
    asset = _logo_asset()
    if asset and WATERMARK_ENABLED:
        uri, _ = asset
        watermark = f'<div class="watermark"><img src="{uri}" style="width:360px;" /></div>'

    header_block = (
        '<div class="report-header">'
        '<div class="report-overline">Research Report</div>'
        f'<h1 class="report-title">{safe_title}</h1>'
        f'<div class="report-meta">Generated {date_str}'
        f'<span class="sep">•</span>{BRAND_NAME}</div>'
        '</div>'
    )
    return f"""<!doctype html>
<html><head>
<meta charset="utf-8">
<title>{safe_title}</title>
{_mathjax_script_tag()}
<style>{css}</style>
</head>
<body>
{watermark}
{header_block}
{body_html}
</body></html>"""