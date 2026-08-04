"""
In-memory cancellation registry for SSE streaming requests.

NOTE:
This is a plain in-process dict. It only works correctly with a single
backend worker/process.

If this service is ever scaled to multiple processes or instances, this
must be replaced with a shared store, for example Redis, so every worker
sees the same cancel flags.
"""

import threading
import time


_lock = threading.Lock()
_flags: dict[str, bool] = {}
_registered_at: dict[str, float] = {}

_MAX_AGE_SECONDS = 60 * 30


def register(request_id: str) -> None:
    with _lock:
        _sweep_stale_locked()
        _flags[request_id] = False
        _registered_at[request_id] = time.time()


def cancel(request_id: str) -> bool:
    """
    Returns True if the request_id was known and got flagged.
    Returns False if unknown.
    """
    with _lock:
        if request_id not in _flags:
            return False

        _flags[request_id] = True
        return True


def is_cancelled(request_id: str) -> bool:
    with _lock:
        return _flags.get(request_id, False)


def cleanup(request_id: str) -> None:
    with _lock:
        _flags.pop(request_id, None)
        _registered_at.pop(request_id, None)


def _sweep_stale_locked() -> None:
    now = time.time()

    stale = [
        rid
        for rid, ts in _registered_at.items()
        if now - ts > _MAX_AGE_SECONDS
    ]

    for rid in stale:
        _flags.pop(rid, None)
        _registered_at.pop(rid, None)