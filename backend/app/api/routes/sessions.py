from datetime import datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.auth import get_current_user
from app.db.database import get_db
from app.db.models import Chat, LibraryPaper, ResearchSession, User

router = APIRouter(prefix="/sessions", tags=["sessions"])


class SessionCreate(BaseModel):
    name: str = Field(default="New Session", min_length=1, max_length=200)


class SessionRead(BaseModel):
    id: UUID
    name: str
    created_at: datetime
    updated_at: datetime
    chat_count: int = 0
    paper_count: int = 0


class SessionUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


def _read(session: ResearchSession, db: DBSession) -> SessionRead:
    return SessionRead(
        id=session.id,
        name=session.name,
        created_at=session.created_at,
        updated_at=session.updated_at,
            chat_count=len(db.scalars(select(Chat).where(Chat.session_id == session.id, Chat.deleted_at.is_(None), Chat.messages.any()).limit(1000)).all()),
        paper_count=len(db.scalars(select(LibraryPaper).where(LibraryPaper.session_id == session.id).limit(1000)).all()),
    )


def _owned(session_id: UUID, user: User, db: DBSession) -> ResearchSession:
    session = db.scalar(select(ResearchSession).where(ResearchSession.id == session_id, ResearchSession.user_id == user.id))
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    return session


@router.get("", response_model=list[SessionRead])
def list_sessions(user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    sessions = db.scalars(select(ResearchSession).where(ResearchSession.user_id == user.id).order_by(ResearchSession.updated_at.desc())).all()
    return [_read(session, db) for session in sessions]


@router.post("", response_model=SessionRead, status_code=201)
def create_session(payload: SessionCreate, user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    session = ResearchSession(id=uuid4(), external_id=f"app-{uuid4()}", user_id=user.id, name=payload.name.strip())
    db.add(session)
    db.commit()
    db.refresh(session)
    return _read(session, db)


@router.get("/{session_id}", response_model=SessionRead)
def get_session(session_id: UUID, user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    return _read(_owned(session_id, user, db), db)


@router.patch("/{session_id}", response_model=SessionRead)
def rename_session(session_id: UUID, payload: SessionUpdate, user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    session = _owned(session_id, user, db)
    session.name = payload.name.strip()
    session.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(session)
    return _read(session, db)


@router.delete("/{session_id}", status_code=204)
def delete_session(session_id: UUID, user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    session = _owned(session_id, user, db)
    db.delete(session)
    db.commit()
