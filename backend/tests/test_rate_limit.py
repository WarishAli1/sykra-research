from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services import rate_limit


def test_development_memory_limiter_returns_retry_after(monkeypatch):
    monkeypatch.setattr(rate_limit.settings, "REDIS_URL", "")
    monkeypatch.setattr(rate_limit.settings, "ENVIRONMENT", "development")
    request = SimpleNamespace(client=SimpleNamespace(host="test-rate-limit"))
    for _ in range(2):
        rate_limit.enforce_rate_limit(request, "test", 2)
    with pytest.raises(HTTPException) as error:
        rate_limit.enforce_rate_limit(request, "test", 2)
    assert error.value.status_code == 429
    assert error.value.headers["Retry-After"]
