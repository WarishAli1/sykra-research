import asyncio
import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from authlib.integrations.httpx_client import AsyncOAuth2Client
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DBSession
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.auth import create_session, get_current_user, hash_token, normalize_email, password_hash, revoke_current_session
from app.config import settings
from app.db.database import get_db
from app.db.models import EmailToken, Session, User
from app.services.email import password_reset_email, send_email, verification_email
from app.services.breached_password import ensure_not_breached

router = APIRouter(prefix="/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)
logger = logging.getLogger(__name__)


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=160)


class UserRead(BaseModel):
    id: str
    email: str
    name: str | None


class EmailPayload(BaseModel):
    email: EmailStr


class ResetPayload(BaseModel):
    token: str = Field(min_length=20, max_length=256)
    password: str = Field(min_length=12, max_length=128)


class ChangePasswordPayload(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


def _new_token(db: DBSession, user: User, purpose: str, ttl: timedelta) -> str:
    raw = secrets.token_urlsafe(32)
    db.add(
        EmailToken(
            user_id=user.id,
            token_hash=hash_token(raw),
            purpose=purpose,
            expires_at=datetime.now(timezone.utc) + ttl,
        )
    )
    db.commit()
    return raw


async def _send_verification(user: User, token: str) -> None:
    url = f"{settings.FRONTEND_PUBLIC_URL}/verify-email?token={token}"
    subject, html, text = verification_email(url)
    await send_email(user.email, subject, html, text)


def public_user(user: User) -> UserRead:
    return UserRead(id=str(user.id), email=user.email, name=user.name)


def _google_configured() -> bool:
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)


@router.post("/signup", response_model=UserRead, status_code=201)
@limiter.limit("5/minute")
async def signup(request: Request, payload: Credentials, response: Response, db: DBSession = Depends(get_db)):
    try:
        ensure_not_breached(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    email = normalize_email(str(payload.email))
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=400, detail="Unable to create account with those details.")
    user = User(email=email, name=payload.name, password_hash=password_hash.hash(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    create_session(db, user, request, response)
    token = _new_token(db, user, "verify_email", timedelta(hours=24))
    try:
        await _send_verification(user, token)
    except Exception as exc:
        logger.error("Verification email delivery failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Account created, but verification email delivery failed.") from exc
    return public_user(user)


@router.post("/login", response_model=UserRead)
@limiter.limit("5/minute")
def login(request: Request, payload: Credentials, response: Response, db: DBSession = Depends(get_db)):
    email = normalize_email(str(payload.email))
    user = db.scalar(select(User).where(User.email == email))
    if not user or not password_hash.verify(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    create_session(db, user, request, response)
    return public_user(user)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: DBSession = Depends(get_db)):
    revoke_current_session(request, db)
    response.delete_cookie(settings.SESSION_COOKIE_NAME, path="/")


@router.post("/logout-all", status_code=204)
def logout_all(response: Response, user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    db.execute(delete(Session).where(Session.user_id == user.id))
    db.commit()
    response.delete_cookie(settings.SESSION_COOKIE_NAME, path="/")


@router.get("/me", response_model=UserRead)
def me(user: User = Depends(get_current_user)):
    return public_user(user)


@router.get("/verify-email")
async def verify_email(token: str = "", db: DBSession = Depends(get_db)):
    record = db.scalar(
        select(EmailToken).where(
            EmailToken.token_hash == hash_token(token),
            EmailToken.purpose == "verify_email",
            EmailToken.used_at.is_(None),
            EmailToken.expires_at > datetime.now(timezone.utc),
        )
    )
    if not record:
        raise HTTPException(status_code=400, detail="Verification link is invalid or expired.")
    user = db.get(User, record.user_id)
    if not user:
        raise HTTPException(status_code=400, detail="Verification link is invalid or expired.")
    now = datetime.now(timezone.utc)
    record.used_at = now
    user.email_verified_at = now
    db.commit()
    return {"status": "verified"}


@router.post("/resend-verification")
@limiter.limit("3/minute")
async def resend_verification(
    request: Request,
    payload: EmailPayload,
    db: DBSession = Depends(get_db),
):
    user = db.scalar(select(User).where(User.email == normalize_email(str(payload.email))))
    if user and not user.email_verified_at:
        token = _new_token(db, user, "verify_email", timedelta(hours=24))
        try:
            await _send_verification(user, token)
        except Exception as exc:
            logger.error("Verification resend failed: %s", type(exc).__name__)
    return {"detail": "If the account can receive verification email, a message will be sent."}


@router.post("/forgot-password")
@limiter.limit("3/minute")
async def forgot_password(
    request: Request,
    payload: EmailPayload,
    db: DBSession = Depends(get_db),
):
    user = db.scalar(select(User).where(User.email == normalize_email(str(payload.email))))
    if user:
        token = _new_token(db, user, "password_reset", timedelta(minutes=30))
        url = f"{settings.FRONTEND_PUBLIC_URL}/reset-password?token={token}"
        subject, html, text = password_reset_email(url)
        try:
            await send_email(user.email, subject, html, text)
        except Exception as exc:
            logger.error("Password reset delivery failed: %s", type(exc).__name__)
    await asyncio.sleep(0)
    return {"detail": "If the account exists, password reset instructions will be sent."}


@router.post("/reset-password")
@limiter.limit("3/minute")
async def reset_password(request: Request, payload: ResetPayload, response: Response, db: DBSession = Depends(get_db)):
    try:
        ensure_not_breached(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    record = db.scalar(
        select(EmailToken).where(
            EmailToken.token_hash == hash_token(payload.token),
            EmailToken.purpose == "password_reset",
            EmailToken.used_at.is_(None),
            EmailToken.expires_at > datetime.now(timezone.utc),
        )
    )
    if not record:
        raise HTTPException(status_code=400, detail="Reset link is invalid or expired.")
    user = db.get(User, record.user_id)
    if not user:
        raise HTTPException(status_code=400, detail="Reset link is invalid or expired.")
    user.password_hash = password_hash.hash(payload.password)
    record.used_at = datetime.now(timezone.utc)
    db.execute(delete(Session).where(Session.user_id == user.id))
    db.commit()
    response.delete_cookie(settings.SESSION_COOKIE_NAME, path="/")
    return {"status": "password_reset"}


@router.post("/change-password")
def change_password(
    request: Request,
    payload: ChangePasswordPayload,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    try:
        ensure_not_breached(payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not password_hash.verify(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")

    raw_token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    current_session = db.scalar(
        select(Session).where(Session.token_hash == hash_token(raw_token or ""))
    )
    if not current_session:
        raise HTTPException(status_code=401, detail="Authentication required.")

    user.password_hash = password_hash.hash(payload.new_password)
    db.execute(
        delete(Session).where(
            Session.user_id == user.id,
            Session.id != current_session.id,
        )
    )
    db.commit()
    return {"status": "password_changed"}


@router.get("/google/start")
def google_start(response: Response):
    if not _google_configured():
        raise HTTPException(status_code=404, detail="Google sign-in is not configured.")
    state = secrets.token_urlsafe(32)
    redirect = RedirectResponse(
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={settings.GOOGLE_CLIENT_ID}"
        f"&redirect_uri={settings.GOOGLE_REDIRECT_URI}"
        "&response_type=code&scope=openid%20email%20profile"
        f"&state={state}"
    )
    redirect.set_cookie(
        "sykra_oauth_state",
        state,
        max_age=600,
        httponly=True,
        secure=settings.SECURE_COOKIES,
        samesite="lax",
        path="/api/auth/google",
    )
    return redirect


@router.get("/google/callback")
async def google_callback(request: Request, response: Response, code: str = "", state: str = "", db: DBSession = Depends(get_db)):
    expected_state = request.cookies.get("sykra_oauth_state")
    if not _google_configured() or not code or not state or not expected_state or not secrets.compare_digest(state, expected_state):
        raise HTTPException(status_code=400, detail="Google sign-in could not be validated.")

    async with AsyncOAuth2Client(
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scope="openid email profile",
    ) as client:
        token = await client.fetch_token(
            "https://oauth2.googleapis.com/token",
            code=code,
            redirect_uri=settings.GOOGLE_REDIRECT_URI,
        )
        userinfo = await client.get("https://openidconnect.googleapis.com/v1/userinfo", token=token)
        userinfo.raise_for_status()
        profile = userinfo.json()

    if not profile.get("email") or profile.get("email_verified") is not True:
        raise HTTPException(status_code=400, detail="Google account email could not be verified.")

    email = normalize_email(profile["email"])
    user = db.scalar(select(User).where(User.email == email))
    if not user:
        user = User(
            email=email,
            name=profile.get("name"),
            password_hash=password_hash.hash(secrets.token_urlsafe(32)),
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    elif not user.email_verified_at:
        user.email_verified_at = datetime.now(timezone.utc)
        db.commit()

    redirect = RedirectResponse(f"{settings.FRONTEND_PUBLIC_URL}/app")
    create_session(db, user, request, redirect)
    redirect.delete_cookie("sykra_oauth_state", path="/api/auth/google")
    return redirect
