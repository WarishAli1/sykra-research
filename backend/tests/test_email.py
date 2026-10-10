import asyncio

from app.services.email import password_reset_email, send_email, verification_email


def test_console_email_provider_is_safe_by_default():
    subject, html, text = verification_email("https://example.test/verify?token=abc")
    assert "Verify" in subject
    assert "example.test" in html
    assert "example.test" in text


def test_send_email_console_backend():
    asyncio.run(
        send_email(
            "user@example.com",
            "Test",
            "<p>Test</p>",
            "Test",
        )
    )


def test_reset_template_mentions_single_use_expiry():
    _, html, text = password_reset_email("https://example.test/reset?token=abc")
    assert "once" in html
    assert "example.test" in text
