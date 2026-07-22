"""
pdf_template.py

Builds the themed HTML shell that answer markdown is rendered into before
being printed to PDF via Playwright + MathJax. Colors match the app's
enterprise palette:

  primary:    Deep Ink Blue  #1F3A5F
  secondary:  Warm Sage      #7A9E8E
  background: #FAFBFC
  text:       #1A1F24

MathJax is vendored locally (see MATHJAX_JS_PATH) rather than loaded from a
CDN, so PDF generation has no external network dependency at request time —
important for an enterprise deployment where export must not silently hang
or fail if a third-party CDN is slow/unreachable.
"""
import os

# Path to the vendored MathJax tex-svg bundle. Set this via the
# MATHJAX_JS_PATH env var in production. Default assumes MathJax was
# installed as a normal npm dependency of the backend service:
#   npm install mathjax@3
# and this points at its es5 SVG-output bundle. tex-svg.js is self-contained
# (no external font/network requests at typeset time), which matters here
# since PDF rendering must not depend on internet access at request time.
MATHJAX_JS_PATH = os.environ.get(
    "MATHJAX_JS_PATH",
    os.path.join(os.getcwd(), "node_modules", "mathjax", "es5", "tex-svg.js"),
)

_THEME = {
    "primary": "#1F3A5F",
    "secondary": "#7A9E8E",
    "background": "#FAFBFC",
    "text": "#1A1F24",
}


def _mathjax_script_tag() -> str:
    """Inline the vendored MathJax bundle directly into the HTML as a
    <script> tag (rather than a <script src=...> pointing at a file path),
    since Playwright's page.set_content() doesn't reliably resolve relative
    file:// script src paths across environments. Inlining guarantees it
    loads regardless of working directory."""
    if not os.path.isfile(MATHJAX_JS_PATH):
        raise FileNotFoundError(
            f"MathJax bundle not found at {MATHJAX_JS_PATH}. "
            "Install it with `npm install mathjax@3` and set MATHJAX_JS_PATH, "
            "or copy es5/tex-svg.js into the expected vendor directory."
        )
    with open(MATHJAX_JS_PATH, "r", encoding="utf-8") as f:
        mathjax_src = f.read()

    config = """
    window.MathJax = {
      tex: {
        inlineMath: [['$', '$']],
        displayMath: [['$$', '$$']],
        processEscapes: true
      },
      svg: { fontCache: 'local' },
      startup: {
        typeset: false
      }
    };
    """
    return f"<script>{config}</script><script>{mathjax_src}</script>"


def build_pdf_html(body_html: str, title: str, latex_style: bool) -> str:
    """Wrap rendered body HTML (from markdown) in a themed document shell.

    latex_style toggles a serif "academic paper" look (matching the existing
    Academic PDF export option) vs. the standard sans-serif enterprise report
    look. Both use the same color theme.
    """
    serif_font = "'Source Serif Pro', Georgia, 'Times New Roman', serif"
    sans_font = "'Inter', 'Segoe UI', Helvetica, Arial, sans-serif"
    body_font = serif_font if latex_style else sans_font
    heading_font = serif_font if latex_style else sans_font

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
{_mathjax_script_tag()}
<style>
  @page {{
    size: Letter;
    margin: 0.9in 0.85in;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{
    margin: 0;
    padding: 0;
    background: {_THEME['background']};
    color: {_THEME['text']};
    font-family: {body_font};
    font-size: 10.5pt;
    line-height: 1.55;
  }}
  .doc-title {{
    font-family: {heading_font};
    font-size: 20pt;
    font-weight: 700;
    color: {_THEME['primary']};
    margin: 0 0 4pt 0;
    text-align: {'center' if latex_style else 'left'};
  }}
  .doc-rule {{
    border: none;
    border-top: 1.5pt solid {_THEME['secondary']};
    margin: 8pt 0 16pt 0;
  }}
  .abstract {{
    font-size: 9.3pt;
    color: #45504f;
    padding: 8pt 18pt;
    margin: 0 0 16pt 0;
    border-left: 3pt solid {_THEME['secondary']};
    background: rgba(122, 158, 142, 0.07);
  }}
  h1, h2, h3, h4 {{
    font-family: {heading_font};
    color: {_THEME['primary']};
    font-weight: 700;
    margin-top: 18pt;
    margin-bottom: 7pt;
    break-after: avoid;
  }}
  h2 {{
    font-size: 13.5pt;
    border-bottom: 0.75pt solid rgba(31,58,95,0.18);
    padding-bottom: 3pt;
  }}
  h3 {{ font-size: 11.5pt; }}
  p {{ margin: 0 0 9pt 0; text-align: justify; }}
  ul, ol {{ margin: 4pt 0 10pt 0; padding-left: 20pt; }}
  li {{ margin-bottom: 3pt; }}
  strong {{ color: {_THEME['primary']}; font-weight: 700; }}
  code {{
    font-family: 'JetBrains Mono', 'Courier New', monospace;
    background: rgba(31,58,95,0.06);
    padding: 1pt 4pt;
    border-radius: 3pt;
    font-size: 9.3pt;
  }}
  a {{ color: {_THEME['primary']}; text-decoration: underline; }}

  /* Tables */
  table {{
    width: 100%;
    border-collapse: collapse;
    margin: 10pt 0 14pt 0;
    font-size: 9.3pt;
    break-inside: avoid;
  }}
  thead tr {{ background: {_THEME['primary']}; }}
  thead th {{
    color: #FAFBFC;
    font-weight: 700;
    text-align: left;
    padding: 6pt 8pt;
    border: 0.5pt solid {_THEME['primary']};
  }}
  tbody td {{
    padding: 5pt 8pt;
    border: 0.5pt solid rgba(31,58,95,0.18);
    vertical-align: top;
  }}
  tbody tr:nth-child(even) {{ background: rgba(122,158,142,0.06); }}

  /* Images / charts */
  figure {{
    margin: 12pt 0;
    text-align: center;
    break-inside: avoid;
  }}
  figure img {{
    max-width: 100%;
    max-height: 4.2in;
    border: 0.75pt solid rgba(31,58,95,0.15);
    border-radius: 4pt;
  }}
  figcaption {{
    font-size: 8.7pt;
    color: #6b7680;
    margin-top: 5pt;
    font-style: italic;
  }}

  /* Math */
  mjx-container {{ margin: 2pt 0; }}
  mjx-container[display="true"] {{
    margin: 10pt 0 !important;
    overflow-x: auto;
  }}

  /* References */
  .references {{
    margin-top: 18pt;
    padding-top: 10pt;
    border-top: 1pt solid {_THEME['secondary']};
  }}
  .references h2 {{ border-bottom: none; }}
  .ref-entry {{
    font-size: 8.8pt;
    line-height: 1.5;
    margin-bottom: 7pt;
    padding-left: 16pt;
    text-indent: -16pt;
    color: #3a4550;
  }}
</style>
</head>
<body>
  <div class="doc-title">{title}</div>
  <hr class="doc-rule">
  {body_html}
</body>
</html>"""