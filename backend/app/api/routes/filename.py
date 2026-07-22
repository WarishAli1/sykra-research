from fastapi import APIRouter, HTTPException
from app.models.schemas import FilenameResponse
from app.services.filename_service import get_filename

router = APIRouter()

@router.get("/filename/{turn_id}", response_model=FilenameResponse)
def get_filename_endpoint(turn_id: str):
    filename = get_filename(turn_id)
    return FilenameResponse(turn_id=turn_id, filename=filename)