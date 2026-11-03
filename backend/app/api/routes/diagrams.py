from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.auth import get_current_user
from app.db.database import get_db
from app.db.models import DiagramDocument, User
from app.services.ownership import require_research_session
from app.models.diagram_schema import DiagramDocumentModel
from app.models.diagram_ai import (
    DiagramAiEditOutput,
    DiagramAiEditRequest,
    DiagramAiGenerateRequest,
    AiDiagramOutput,
)
from app.services.diagram_ai import edit as edit_diagram, generate as generate_diagram
from app.services.rate_limit import enforce_rate_limit
from fastapi import Request

router = APIRouter()


class DiagramDocumentRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    document: DiagramDocumentModel


@router.post("/ai/generate", response_model=AiDiagramOutput)
def ai_generate(
    request: Request,
    payload: DiagramAiGenerateRequest,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    require_research_session(db, user, payload.session_id)
    enforce_rate_limit(request, "diagram-ai", 10)
    return generate_diagram(payload.diagram_type, payload.instruction)


@router.post("/ai/edit", response_model=DiagramAiEditOutput)
def ai_edit(
    request: Request,
    payload: DiagramAiEditRequest,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    require_research_session(db, user, payload.session_id)
    enforce_rate_limit(request, "diagram-ai", 10)
    return edit_diagram(payload.document.model_dump(by_alias=True), payload.instruction)


def _serialize(record: DiagramDocument) -> dict:
    validated = DiagramDocumentModel.model_validate(record.document)
    return {
        "id": str(record.id),
        "session_id": str(record.session_id),
        "title": record.title,
        "document": validated.model_dump(by_alias=True),
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


@router.post("")
def create_document(
    request: DiagramDocumentRequest,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    session = require_research_session(db, user, request.session_id)
    record = DiagramDocument(
        id=uuid4(),
        session_id=session.id,
        user_id=user.id,
        title=request.title,
        document=request.document.model_dump(by_alias=True),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return _serialize(record)


@router.get("/{document_id}")
def get_document(
    document_id: UUID,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    record = db.scalar(
        select(DiagramDocument).where(
            DiagramDocument.id == document_id,
            DiagramDocument.user_id == user.id,
        )
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return _serialize(record)


@router.patch("/{document_id}")
def update_document(
    document_id: UUID,
    request: DiagramDocumentRequest,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    record = db.scalar(
        select(DiagramDocument).where(
            DiagramDocument.id == document_id,
            DiagramDocument.user_id == user.id,
        )
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    session = require_research_session(db, user, request.session_id)
    if record.session_id != session.id:
        raise HTTPException(status_code=400, detail="Document session cannot be changed.")
    record.title = request.title
    record.document = request.document.model_dump(by_alias=True)
    db.commit()
    db.refresh(record)
    return _serialize(record)


@router.get("/session/{session_id}")
def list_documents(
    session_id: str,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    session = require_research_session(db, user, session_id)
    records = db.scalars(
        select(DiagramDocument)
        .where(DiagramDocument.session_id == session.id, DiagramDocument.user_id == user.id)
        .order_by(DiagramDocument.updated_at.desc())
    ).all()
    return {"documents": [_serialize(record) for record in records]}
