import re
import unicodedata

_DASH_CHARS = re.compile(
    "[\u2010\u2011\u2012\u2013\u2014\u2015\u2212\u00AD\u207B\u208B]"
)
_FENCE_RE = re.compile(r"^[ \t]*\$\$[ \t]*$")
_PROSE_BOUNDARY_RE = re.compile(r"(?:^[ \t]*$)|(?:^[ \t]*#{1,6}\s)")

def normalize_math_fences(md: str) -> str:
    s = md
    for _ in range(2):
        s = re.sub(r"([^\n])\$\$", r"\1\n$$", s)
        s = re.sub(r"\$\$([^\n])", r"$$\n\1", s)
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
                ensure_blank(); out.append("$$"); in_math = True
            else:
                out.append("$$"); in_math = False; ensure_blank()
        elif in_math and _PROSE_BOUNDARY_RE.match(line):
            out.append("$$"); in_math = False; out.append(line)
            if line.strip() != "":
                ensure_blank()
        else:
            out.append(line)
        i += 1
    if in_math:
        out.append("$$")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out))

def normalize_dashes(text: str) -> str:
    return _DASH_CHARS.sub("-", text)


def sanitize_abstract(text: str, max_chars: int = 300) -> str:
    if not text:
        return "No abstract available."

    text = text[:max_chars].strip()

    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')

    text = re.sub(r'\([^)]*[A-Z][^)]*\)', '', text)

    text = re.sub(r'\b\d+(\.\d+)+\s+', '', text)

    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)

    text = re.sub(r'\s+', ' ', text).strip()

    if len(text) < 25:
        return "[Abstract contains mostly mathematical notation]"

    return text