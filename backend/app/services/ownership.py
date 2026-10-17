from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.db.models import ResearchSession, User


def require_research_session(
    db: DBSession,
    user: User,
    external_id: str,
    *,
    create: bool = False,
) -> ResearchSession:
    """Resolve a session by primary key (UUID) first, then by legacy external_id."""
    if not external_id or len(external_id) > 200:
        raise HTTPException(status_code=404, detail="Resource not found.")

    record = None

    # 1) New-style: the URL carries ResearchSession.id
    try:
        pk = UUID(external_id)
    except ValueError:
        pk = None
    if pk is not None:
        record = db.scalar(select(ResearchSession).where(ResearchSession.id == pk))

    # 2) Legacy: external_id
    if record is None:
        record = db.scalar(
            select(ResearchSession).where(ResearchSession.external_id == external_id)
        )

    if record:
        if record.user_id != user.id:
            raise HTTPException(status_code=404, detail="Resource not found.")
        return record

    if not create:
        raise HTTPException(status_code=404, detail="Resource not found.")

    record = ResearchSession(
        **({"id": pk} if pk is not None else {}),
        external_id=external_id,
        user_id=user.id,
    )
    
    db.add(record)
    db.commit()
    db.refresh(record)
    return record