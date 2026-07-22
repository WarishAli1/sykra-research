import threading
from keybert import KeyBERT

_store = {}
_lock = threading.Lock()
kw_model = KeyBERT()

def generate_filename(turn_id: str, text: str) -> str:
    try:
        keywords = kw_model.extract_keywords(
            text,
            keyphrase_ngram_range=(1, 3),
            stop_words="english",
            top_n=1,
        )

        slug = keywords[0][0].lower().replace(" ", "-") if keywords else "research-answer"

        with _lock:
            _store[turn_id] = slug

        return slug

    except Exception as e:
        print(f"[filename] failed: {type(e).__name__}: {e} | text_len={len(text)} | text_preview={text[:80]!r}")
        return "research-answer"

def get_filename(turn_id: str) -> str | None:
    """Poll this to get the generated filename."""
    with _lock:
        return _store.get(turn_id)