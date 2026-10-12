from fastapi import HTTPException

from app.config import settings


def read_pdf_content(content: bytes) -> bytes:
    if len(content) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Uploaded file is too large.")
    if not content.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid PDF.")
    return content
