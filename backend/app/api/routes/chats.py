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
    title: str
    created_at: datetime
    updated_at: datetime


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
    limit: int = Query(50, ge=1, le=100),
    before: datetime | None = Query(None),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    query = select(Chat).where(Chat.user_id == user.id, Chat.deleted_at.is_(None))
    if before is not None:
        query = query.where(Chat.updated_at < before)
    return list(db.scalars(query.order_by(Chat.updated_at.desc()).limit(limit)))


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


@router.delete("/{chat_id}", status_code=204)
def delete_chat(chat_id: UUID, user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    chat = db.scalar(select(Chat).where(Chat.id == chat_id, Chat.user_id == user.id, Chat.deleted_at.is_(None)))
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found.")
    chat.deleted_at = datetime.now(timezone.utc)
    db.commit()
