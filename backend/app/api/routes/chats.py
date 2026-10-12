from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.auth import get_current_user
from app.db.database import get_db
from app.db.models import Chat, Message, User

router = APIRouter(prefix="/chats", tags=["chats"])


class ChatRead(BaseModel):
    id: UUID
    session_id: UUID | None = None
    title: str
    created_at: datetime
    updated_at: datetime
    pinned_at: datetime | None = None
    session_name: str | None = None


class MessageRead(BaseModel):
    id: UUID
    role: str
    content: str
    citations: dict
    status: str
    created_at: datetime


class RenamePayload(BaseModel):
    title: str = Field(min_length=1, max_length=200)


@router.get("", response_model=list[ChatRead])
def list_chats(
    session_id: UUID | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    before: datetime | None = Query(None),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    query = select(Chat).where(Chat.user_id == user.id, Chat.deleted_at.is_(None))
    if session_id is not None:
        query = query.where(Chat.session_id == session_id)
    if before is not None:
        query = query.where(Chat.updated_at < before)
    chats = list(db.scalars(query.order_by(Chat.pinned_at.desc().nullslast(), Chat.updated_at.desc()).limit(limit)))
    return [
        ChatRead(
            id=chat.id,
            session_id=chat.session_id,
            title=chat.title,
            created_at=chat.created_at,
            updated_at=chat.updated_at,
            pinned_at=chat.pinned_at,
            session_name=chat.research_session.name if chat.research_session else None,
        )
        for chat in chats
    ]


@router.get("/{chat_id}", response_model=list[MessageRead])
def get_chat(chat_id: UUID, user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    chat = db.scalar(select(Chat).where(Chat.id == chat_id, Chat.user_id == user.id, Chat.deleted_at.is_(None)))
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found.")
    return list(db.scalars(select(Message).where(Message.chat_id == chat.id).order_by(Message.created_at.asc())))


@router.patch("/{chat_id}", response_model=ChatRead)
def rename_chat(chat_id: UUID, payload: RenamePayload, user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    chat = db.scalar(select(Chat).where(Chat.id == chat_id, Chat.user_id == user.id, Chat.deleted_at.is_(None)))
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found.")
    chat.title = payload.title.strip()
    db.commit()
    db.refresh(chat)
    return chat


@router.patch("/{chat_id}/pin", response_model=ChatRead)
def toggle_pin_chat(chat_id: UUID, user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    chat = db.scalar(select(Chat).where(Chat.id == chat_id, Chat.user_id == user.id, Chat.deleted_at.is_(None)))
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found.")
    chat.pinned_at = None if chat.pinned_at else datetime.now(timezone.utc)
    db.commit()
    db.refresh(chat)
    return chat


@router.delete("/{chat_id}", status_code=204)
def delete_chat(chat_id: UUID, user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    chat = db.scalar(select(Chat).where(Chat.id == chat_id, Chat.user_id == user.id, Chat.deleted_at.is_(None)))
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found.")
    chat.deleted_at = datetime.now(timezone.utc)
    db.commit()
