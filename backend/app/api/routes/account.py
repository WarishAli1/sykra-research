from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.auth import get_current_user, password_hash
from app.config import settings
from app.db.database import get_db
from app.db.models import Chat, LibraryPaper, ResearchSession, UploadedFile, User
from app.services.storage import LocalPrivateStorage

router = APIRouter(prefix="/account", tags=["account"])
storage = LocalPrivateStorage(settings.STORAGE_ROOT)


class DeleteAccountPayload(BaseModel):
    password: str = Field(min_length=1, max_length=128)


@router.get("/export")
def export_account(user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    chats = db.scalars(select(Chat).where(Chat.user_id == user.id)).all()
    papers = db.scalars(select(LibraryPaper).where(LibraryPaper.user_id == user.id)).all()
    payload = {
        "user": {"id": str(user.id), "email": user.email, "name": user.name},
        "chats": [
            {
                "id": str(chat.id),
                "title": chat.title,
                "created_at": chat.created_at.isoformat(),
                "updated_at": chat.updated_at.isoformat(),
                "deleted_at": chat.deleted_at.isoformat() if chat.deleted_at else None,
                "messages": [
                    {
                        "id": str(message.id),
                        "role": message.role,
                        "content": message.content,
                        "citations": message.citations,
                        "status": message.status,
                        "created_at": message.created_at.isoformat(),
                    }
                    for message in chat.messages
                ],
            }
            for chat in chats
        ],
        "library": [
            {
                "id": str(paper.id),
                "title": paper.title,
                "link": paper.link,
                "metadata": paper.paper_metadata,
                "created_at": paper.created_at.isoformat(),
                "updated_at": paper.updated_at.isoformat(),
            }
            for paper in papers
        ],
    }
    return JSONResponse(payload, headers={"Content-Disposition": 'attachment; filename="sykra-account-export.json"'})


@router.delete("")
def delete_account(
    request: Request,
    response: Response,
    payload: DeleteAccountPayload,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    if not password_hash.verify(payload.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Password is incorrect.")

    files = db.scalars(select(UploadedFile).where(UploadedFile.user_id == user.id)).all()
    sessions = db.scalars(select(ResearchSession).where(ResearchSession.user_id == user.id)).all()
    for uploaded in files:
        session = next((item for item in sessions if item.id == uploaded.session_id), None)
        if session:
            storage.delete(session.external_id, uploaded.stored_filename)

    db.delete(user)
    db.commit()
    response.delete_cookie(settings.SESSION_COOKIE_NAME, path="/")
    return {"status": "account_deleted"}
