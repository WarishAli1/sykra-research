import time
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session as DBSession

from app.auth import get_current_user
from app.db.database import get_db
from app.db.models import User

router = APIRouter(tags=["avatar"])
ALLOWED_HOSTS = {"lh3.googleusercontent.com", "googleusercontent.com"}
_cache: dict[tuple[str, str], tuple[float, str, bytes]] = {}


@router.get("/avatar")
async def avatar(user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    del db
    if not user.image:
        raise HTTPException(status_code=404, detail="Avatar not available.")
    parsed = urlparse(user.image)
    if parsed.scheme != "https" or not parsed.hostname or not any(parsed.hostname == host or parsed.hostname.endswith(f".{host}") for host in ALLOWED_HOSTS):
        raise HTTPException(status_code=404, detail="Avatar source is not supported.")
    cache_key = (str(user.id), user.image)
    cached = _cache.get(cache_key)
    if cached and cached[0] > time.time() and cached[1]:
        return Response(content=cached[2], media_type=cached[1], headers={"Cache-Control": "private, max-age=86400"})
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
            upstream = await client.get(user.image)
            upstream.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Avatar could not be fetched.") from exc
    final_host = urlparse(str(upstream.url)).hostname
    if not final_host or not any(final_host == host or final_host.endswith(f".{host}") for host in ALLOWED_HOSTS):
        raise HTTPException(status_code=502, detail="Avatar redirect was not supported.")
    content_type = upstream.headers.get("content-type", "image/jpeg").split(";")[0]
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=502, detail="Avatar response was not an image.")
    _cache[cache_key] = (time.time() + 86400, content_type, upstream.content)
    return Response(content=upstream.content, media_type=content_type, headers={"Cache-Control": "private, max-age=86400"})
