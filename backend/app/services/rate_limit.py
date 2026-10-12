import time
from collections import defaultdict
from threading import Lock

import redis
from fastapi import HTTPException, Request

from app.config import settings

_memory: dict[str, tuple[int, float]] = defaultdict(lambda: (0, 0.0))
_lock = Lock()
_redis = None


def _client():
    global _redis
    if not settings.REDIS_URL:
        return None
    if _redis is None:
        _redis = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


def enforce_rate_limit(request: Request, scope: str, limit: int, window_seconds: int = 60) -> None:
    identity = request.client.host if request.client else "unknown"
    key = f"ratelimit:{scope}:{identity}"
    retry_after = window_seconds

    client = _client()
    if client is not None:
        try:
            current = client.incr(key)
            if current == 1:
                client.expire(key, window_seconds)
            if current > limit:
                raise HTTPException(
                    status_code=429,
                    detail="Too many requests.",
                    headers={"Retry-After": str(retry_after)},
                )
            return
        except redis.RedisError:
            if settings.ENVIRONMENT != "development":
                raise HTTPException(status_code=503, detail="Rate limiting is temporarily unavailable.")

    if settings.ENVIRONMENT != "development" and not settings.REDIS_URL:
        raise HTTPException(status_code=503, detail="Rate limiting is not configured.")

    now = time.monotonic()
    with _lock:
        count, expires = _memory[key]
        if now >= expires:
            count, expires = 0, now + window_seconds
        count += 1
        _memory[key] = (count, expires)
        if count > limit:
            raise HTTPException(
                status_code=429,
                detail="Too many requests.",
                headers={"Retry-After": str(max(1, int(expires - now)))},
            )
