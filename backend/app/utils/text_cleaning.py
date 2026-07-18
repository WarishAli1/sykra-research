import re
import unicodedata

_DASH_CHARS = re.compile(
    "[\u2010\u2011\u2012\u2013\u2014\u2015\u2212\u00AD\u207B\u208B]"
)


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
