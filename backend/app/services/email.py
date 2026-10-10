import logging
from dataclasses import dataclass

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    html: str
    text: str


async def send_email(to: str, subject: str, html: str, text: str) -> None:
    message = EmailMessage(to=to, subject=subject, html=html, text=text)
    provider = settings.EMAIL_PROVIDER.casefold()

    if provider == "console":
        logger.info("Development email queued: recipient=%s subject=%s", message.to, message.subject)
        return

    if provider != "resend":
        raise RuntimeError("Unsupported email provider.")
    if not settings.RESEND_API_KEY or not settings.EMAIL_FROM:
        raise RuntimeError("Resend email configuration is incomplete.")

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
            json={
                "from": settings.EMAIL_FROM,
                "to": [message.to],
                "subject": message.subject,
                "html": message.html,
                "text": message.text,
            },
        )
        response.raise_for_status()


def verification_email(url: str) -> tuple[str, str, str]:
    subject = "Verify your Sykra Research email"
    text = f"Verify your Sykra Research email by opening this link:\n\n{url}\n"
    html = (
        "<p>Verify your Sykra Research email to finish setting up your account.</p>"
        f'<p><a href="{url}">Verify email</a></p>'
    )
    return subject, html, text


def password_reset_email(url: str) -> tuple[str, str, str]:
    subject = "Reset your Sykra Research password"
    text = f"Reset your Sykra Research password by opening this link:\n\n{url}\n"
    html = (
        "<p>We received a request to reset your Sykra Research password.</p>"
        f'<p><a href="{url}">Reset password</a></p>'
        "<p>This link expires soon and can be used only once.</p>"
    )
    return subject, html, text
