import asyncio
import re
from uuid import UUID

from sqlalchemy import select

from app.db.database import SessionLocal
from app.db.models import Chat


def _title_from_query(query: str) -> str:
    compact = re.sub(r"\s+", " ", query).strip()
    return compact[:80] or "New chat"


def _persist_title(chat_id: UUID, query: str) -> None:
    db = SessionLocal()
    try:
        chat = db.scalar(select(Chat).where(Chat.id == chat_id, Chat.deleted_at.is_(None)))
        if chat and chat.title == "New chat":
            chat.title = _title_from_query(query)
            db.commit()
    finally:
        db.close()


def schedule_title_generation(chat_id: UUID, query: str) -> None:
    asyncio.create_task(asyncio.to_thread(_persist_title, chat_id, query))
