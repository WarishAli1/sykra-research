import asyncio
import threading
from concurrent.futures import Future


_sync_lock = threading.Lock()
_inflight_sync: dict[str, Future] = {}

_async_lock: asyncio.Lock | None = None
_inflight_async: dict[str, asyncio.Future] = {}


def _get_async_lock() -> asyncio.Lock:
    global _async_lock
    if _async_lock is None:
        _async_lock = asyncio.Lock()
    return _async_lock


def execute_once(key: str, fn, timeout: float = 60.0):
    """
    Sync request coalescing.

    If another thread is already computing `key`, wait for its result.
    """
    with _sync_lock:
        future = _inflight_sync.get(key)

        if future is None:
            future = Future()
            _inflight_sync[key] = future
            owner = True
        else:
            owner = False

    if not owner:
        return future.result(timeout=timeout)

    try:
        result = fn()
        future.set_result(result)
        return result
    except Exception as e:
        future.set_exception(e)
        raise
    finally:
        with _sync_lock:
            _inflight_sync.pop(key, None)


async def execute_once_async(key: str, coro_fn, timeout: float = 60.0):
    """
    Async request coalescing.

    If another coroutine is already computing `key`, wait for its result.
    """
    lock = _get_async_lock()

    async with lock:
        future = _inflight_async.get(key)

        if future is None:
            loop = asyncio.get_running_loop()
            future = loop.create_future()
            _inflight_async[key] = future
            owner = True
        else:
            owner = False

    if not owner:
        return await asyncio.wait_for(future, timeout=timeout)

    try:
        result = await coro_fn()
        future.set_result(result)
        return result
    except Exception as e:
        future.set_exception(e)
        raise
    finally:
        async with lock:
            _inflight_async.pop(key, None)