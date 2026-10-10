import logging
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.auth import hash_token
from app.services import malware_scanner
from app.services.rate_limit import enforce_rate_limit
from app.services.upload_validation import read_pdf_content


def test_session_tokens_are_stored_as_hashes():
    raw = "test-secret-token"
    assert hash_token(raw) != raw
    assert len(hash_token(raw)) == 64


def test_fake_and_oversized_uploads_are_rejected(monkeypatch):
    monkeypatch.setattr("app.config.settings.MAX_UPLOAD_BYTES", 8)
    with pytest.raises(HTTPException) as fake:
        read_pdf_content(b"not-pdf")
    assert fake.value.status_code == 400
    with pytest.raises(HTTPException) as oversized:
        read_pdf_content(b"%PDF-12345")
    assert oversized.value.status_code == 413


def test_production_rate_limiting_requires_redis(monkeypatch):
    monkeypatch.setattr("app.services.rate_limit.settings.REDIS_URL", "")
    monkeypatch.setattr("app.services.rate_limit.settings.ENVIRONMENT", "production")
    request = SimpleNamespace(client=SimpleNamespace(host="security-test"))
    with pytest.raises(HTTPException) as error:
        enforce_rate_limit(request, "production-test", 1)
    assert error.value.status_code == 503


def test_scanner_does_not_log_file_content(caplog, monkeypatch):
    scanner = malware_scanner.MalwareScanner(enabled=True, host="invalid", port=3310)

    def fail(*args, **kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr(malware_scanner, "clamd", None, raising=False)
    with caplog.at_level(logging.ERROR):
        with pytest.raises(RuntimeError):
            scanner.scan_bytes(b"PRIVATE MESSAGE CONTENT")
    assert "PRIVATE MESSAGE CONTENT" not in caplog.text
