import asyncio
import json
import math
import re
from typing import Generator
from app.config import settings

NODE_LABELS = {
    "plan_query": "Planning search strategy...",
    "plan_report": "Planning report structure...",
    "search": "Searching arXiv and OpenAlex...",
    "retrieve_uploaded": "Checking uploaded documents...",
    "validate": "Validating paper metadata...",
    "rank": "Ranking and deduplicating results...",
    "quick_preview": "Drafting quick answer...",
    "summarize": "Synthesizing full answer...",
    "critique": "Checking answer coverage...",
    "revise": "Refining the answer...",
    "after_critique": "Preparing final answer...",
    "cite": "Formatting citations...",
    "answer_ready": "Answer ready.",
}

_CHUNK_PATTERN = re.compile(r"\S+\s*")

_section_queues: dict[str, asyncio.Queue] = {}
_section_loops: dict[str, asyncio.AbstractEventLoop] = {}


def sse_event(event_type: str, **fields) -> str:
    payload = {"type": event_type, **fields}
    return f"data: {json.dumps(payload)}\n\n"


def notice_event(message: str) -> str:
    return sse_event("notice", message=message)


def progress_event(
    node: str,
    detail: str | None = None,
    items: list[str] | None = None,
) -> str:
    label = NODE_LABELS.get(node, f"Running {node}...")
    fields = {
        "stage": node,
        "label": label,
    }
    if detail is not None:
        fields["detail"] = detail
    if items is not None:
        fields["items"] = items
    return sse_event("progress", **fields)


def stream_text_chunks(
    text: str,
    cancel_check=None,
    kind: str = "final",
) -> Generator[str, None, bool]:
    """Sync SSE token streamer (backwards compat)."""
    words = _CHUNK_PATTERN.findall(text or "")
    if not words:
        return True
    buf = []
    total = len(words)
    words_per_frame = 3
    num_frames = math.ceil(total / words_per_frame)
    target_seconds = min(9.0, max(2.5, total / 50.0))
    delay = target_seconds / num_frames if num_frames else 0.0
    delay = min(0.15, max(0.008, delay))
    import time
    for i, word in enumerate(words):
        buf.append(word)
        if len(buf) >= words_per_frame or i == total - 1:
            if cancel_check is not None and cancel_check():
                return False
            yield sse_event("token", text="".join(buf), kind=kind)
            buf = []
            if delay > 0:
                time.sleep(delay)
    return True


async def stream_text_chunks_async(
    text: str,
    cancel_check=None,
    kind: str = "final",
    status: dict | None = None,
):
    """
    Async SSE token streamer with BACKEND-DRIVEN typewriter pacing.
    Tokens arrive gradually (~50 wps, clamped 2.5s–9s total).
    The frontend renders tokens as they arrive — NO client-side typewriter.
    """
    words = _CHUNK_PATTERN.findall(text or "")
    if not words:
        if status is not None:
            status["completed"] = True
        return

    total = len(words)
    words_per_frame = 3
    num_frames = math.ceil(total / words_per_frame)

    target_seconds = min(9.0, max(2.5, total / 50.0))
    delay = target_seconds / num_frames if num_frames else 0.0
    delay = min(0.15, max(0.008, delay))

    buf: list[str] = []
    for i, word in enumerate(words):
        buf.append(word)
        if len(buf) >= words_per_frame or i == total - 1:
            if cancel_check is not None and cancel_check():
                if status is not None:
                    status["completed"] = False
                return
            yield sse_event("token", text="".join(buf), kind=kind)
            buf = []
            if delay > 0:
                await asyncio.sleep(delay)

    if status is not None:
        status["completed"] = True


def bridge_register(request_id: str, loop: asyncio.AbstractEventLoop) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _section_queues[request_id] = q
    _section_loops[request_id] = loop
    return q


def bridge_push(request_id: str, event: tuple) -> None:
    """Thread-safe: call from any sync worker thread."""
    q = _section_queues.get(request_id)
    loop = _section_loops.get(request_id)
    if q is not None and loop is not None:
        loop.call_soon_threadsafe(q.put_nowait, event)


async def bridge_get(request_id: str, timeout: float = 0.15):
    """Async: returns the next event tuple, or None on timeout."""
    q = _section_queues.get(request_id)
    if q is None:
        return None
    try:
        return await asyncio.wait_for(q.get(), timeout=timeout)
    except asyncio.TimeoutError:
        return None


def bridge_cleanup(request_id: str) -> None:
    _section_queues.pop(request_id, None)
    _section_loops.pop(request_id, None)


async def stream_section_words(
    text: str,
    cancel_check=None,
    kind: str = "final",
):
    """
    Stream a completed section as paced word-chunks.
    Faster than final-answer pacing since sections arrive during generation.
    """
    words = _CHUNK_PATTERN.findall(text or "")
    if not words:
        return

    total = len(words)
    words_per_frame = 3
    num_frames = math.ceil(total / words_per_frame)

    target_seconds = min(6.0, max(1.5, total / 60.0))
    delay = target_seconds / num_frames if num_frames else 0.0
    delay = min(0.12, max(0.008, delay))

    buf: list[str] = []
    for i, word in enumerate(words):
        buf.append(word)
        if len(buf) >= words_per_frame or i == total - 1:
            if cancel_check is not None and cancel_check():
                return
            yield sse_event("token", text="".join(buf), kind=kind)
            buf = []
            if delay > 0:
                await asyncio.sleep(delay)