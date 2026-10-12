import hashlib
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def is_breached(password: str) -> bool:
    if not settings.HIBP_CHECK_ENABLED:
        return False

    digest = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
    prefix, suffix = digest[:5], digest[5:]
    try:
        response = httpx.get(
            f"https://api.pwnedpasswords.com/range/{prefix}",
            headers={"Add-Padding": "true"},
            timeout=5,
        )
        response.raise_for_status()
        return any(line.split(":", 1)[0].strip() == suffix for line in response.text.splitlines())
    except httpx.HTTPError as exc:
        logger.warning("Breached-password check unavailable: %s", type(exc).__name__)
        return False


def ensure_not_breached(password: str) -> None:
    if is_breached(password):
        raise ValueError("Choose a password that has not appeared in a known breach.")
