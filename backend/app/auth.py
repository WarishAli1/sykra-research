from datetime import datetime, timedelta, timezone
import hashlib
import secrets

from fastapi import Depends, HTTPException, Request, Response, status
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.db.database import get_db
from app.db.models import Session, User

password_hash = PasswordHash.recommended()


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        settings.SESSION_COOKIE_NAME,
        token,
        max_age=settings.SESSION_TTL_SECONDS,
        httponly=True,
        secure=settings.SECURE_COOKIES,
        samesite="lax",
        path="/",
    )


def create_session(db: DBSession, user: User, request: Request, response: Response) -> None:
    raw_token = secrets.token_urlsafe(48)
    db.add(Session(
        user_id=user.id,
        token_hash=hash_token(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=settings.SESSION_TTL_SECONDS),
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent", "")[:512],
    ))
    db.commit()
    set_session_cookie(response, raw_token)


def get_current_user(request: Request, db: DBSession = Depends(get_db)) -> User:
    raw_token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    session = db.scalar(select(Session).where(Session.token_hash == hash_token(raw_token)))
    if not session or session.expires_at <= datetime.now(timezone.utc):
        if session:
            db.delete(session)
            db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    user = db.get(User, session.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    return user


def revoke_current_session(request: Request, db: DBSession) -> None:
    raw_token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if raw_token:
        session = db.scalar(select(Session).where(Session.token_hash == hash_token(raw_token)))
        if session:
            db.delete(session)
            db.commit()
