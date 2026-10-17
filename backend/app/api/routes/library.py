from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AnyHttpUrl, BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.auth import get_current_user
from app.db.database import get_db
from app.db.models import LibraryPaper, ResearchSession, User

router = APIRouter(prefix="/library", tags=["library"])


class PaperPayload(BaseModel):
    session_id: UUID | None = None
    title: str = Field(min_length=1, max_length=1000)
    link: AnyHttpUrl
    metadata: dict = Field(default_factory=dict)


@router.get("")
def list_papers(session_id: UUID | None = Query(None), user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    query = select(LibraryPaper).where(LibraryPaper.user_id == user.id)
    if session_id is not None:
        query = query.where(LibraryPaper.session_id == session_id)
    return list(db.scalars(query.order_by(LibraryPaper.updated_at.desc())))


@router.get("/session/{session_id}/papers")
def session_papers(session_id: UUID, chat_id: UUID | None = Query(None), user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    q = select(LibraryPaper).where(LibraryPaper.user_id == user.id, LibraryPaper.session_id == session_id)
    if chat_id is not None:
        q = q.where(LibraryPaper.chat_id == chat_id)
    rows = db.scalars(q.order_by(LibraryPaper.created_at.asc()))
    out = []
    for r in rows:
        m = r.paper_metadata or {}
        out.append({
            "title": r.title, "link": r.link,
            "authors": m.get("authors", []), "summary": m.get("summary", ""),
            "published": m.get("published"), "relevance_score": m.get("relevance_score"),
            "source": m.get("source"), "is_uploaded": m.get("is_uploaded", False),
            "file_url": m.get("file_url"),
        })
    return out


@router.post("", status_code=201)
def save_paper(payload: PaperPayload, user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    if payload.session_id is not None and not db.scalar(select(ResearchSession).where(ResearchSession.id == payload.session_id, ResearchSession.user_id == user.id)):
        raise HTTPException(status_code=404, detail="Session not found.")
    paper = LibraryPaper(session_id=payload.session_id, user_id=user.id, title=payload.title.strip(), link=str(payload.link), paper_metadata=payload.metadata)
    db.add(paper)
    db.commit()
    db.refresh(paper)
    return paper


@router.delete("/{paper_id}", status_code=204)
def delete_paper(paper_id: UUID, user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    paper = db.scalar(select(LibraryPaper).where(LibraryPaper.id == paper_id, LibraryPaper.user_id == user.id))
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found.")
    db.delete(paper)
    db.commit()
