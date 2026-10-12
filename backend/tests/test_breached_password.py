import hashlib

from app.services import breached_password


def test_hibp_uses_k_anonymity_and_detects_suffix(monkeypatch):
    calls = {}

    suffix = hashlib.sha1(b"password").hexdigest().upper()[5:]

    class Response:
        text = f"{suffix}:4\r\n"

        def raise_for_status(self):
            return None

    def fake_get(url, **kwargs):
        calls["url"] = url
        calls["kwargs"] = kwargs
        return Response()

    monkeypatch.setattr(breached_password.httpx, "get", fake_get)
    monkeypatch.setattr(breached_password.settings, "HIBP_CHECK_ENABLED", True)
    assert breached_password.is_breached("password") is True
    assert calls["url"].startswith("https://api.pwnedpasswords.com/range/")
    assert len(calls["url"].rsplit("/", 1)[-1]) == 5


def test_hibp_fails_open(monkeypatch):
    def fake_get(*args, **kwargs):
        raise breached_password.httpx.ConnectError("offline")

    monkeypatch.setattr(breached_password.httpx, "get", fake_get)
    monkeypatch.setattr(breached_password.settings, "HIBP_CHECK_ENABLED", True)
    assert breached_password.is_breached("some password") is False
