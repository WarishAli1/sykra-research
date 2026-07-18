import json
import re
import time
from typing import Generator, Iterable

NODE_LABELS = {
    "plan_query": "Planning search strategy...",
    "search": "Searching arXiv and OpenAlex...",
    "retrieve_uploaded": "Checking uploaded documents...",
    "validate": "Validating paper metadata...",
    "rank": "Ranking and deduplicating results...",
    "summarize": "Synthesizing the answer...",
    "cite": "Formatting citations...",
    "graph_write": "Updating the knowledge graph...",
}

_CHUNK_PATTERN = re.compile(r"\S+\s*")
_CHUNK_DELAY_SECONDS = 0.02
_WORDS_PER_FRAME = 3


def sse_event(event_type: str, **fields) -> str:
    payload = {"type": event_type, **fields}
    return f"data: {json.dumps(payload)}\n\n"


def progress_event(node: str) -> str:
    label = NODE_LABELS.get(node, f"Running {node}...")
    return sse_event("progress", node=node, label=label)


def stream_text_chunks(
    text: str,
    is_cancelled: "Iterable[bool] | None" = None,
    cancel_check=None,
) -> Generator[str, None, bool]:
    """
    Yields SSE 'token' events for `text`, a few words at a time, sleeping
    briefly between frames. Checks cancel_check() (a zero-arg callable
    returning bool) between frames and stops early if it becomes True.

    Returns True if it completed, False if it was cancelled partway through.
    """
    words = _CHUNK_PATTERN.findall(text)
    if not words:
        return True

    buf = []
    for i, word in enumerate(words):
        buf.append(word)
        if len(buf) >= _WORDS_PER_FRAME or i == len(words) - 1:
            if cancel_check is not None and cancel_check():
                return False
            yield sse_event("token", text="".join(buf))
            buf = []
            time.sleep(_CHUNK_DELAY_SECONDS)

    return True
