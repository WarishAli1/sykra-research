from fastapi import APIRouter, UploadFile, File
from app.models.schemas import UploadResponse
import fitz

router = APIRouter()

@router.post("/upload", response_model=UploadResponse)
async def upload_pdf(file: UploadFile = File(...)):
    content = await file.read()
    doc = fitz.open(stream=content, filetype="pdf")
    text = "\n".join(page.get_text() for page in doc)
    doc.close()
    return UploadResponse(filename=file.filename, chunks_indexed=0, status="parsed, indexing pending")
