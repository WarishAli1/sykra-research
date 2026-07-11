from fastapi import APIRouter, UploadFile, File
from app.models.schemas import UploadResponse
from app.services.vector_store import vector_store
import fitz

router = APIRouter()

@router.post("/upload", response_model=UploadResponse)
async def upload_pdf(file: UploadFile = File(...), session_id: str = "default"):
    content = await file.read()
    doc = fitz.open(stream=content, filetype="pdf")
    text = "\n".join(page.get_text() for page in doc)
    doc.close()

    paper = {
        "title": file.filename,
        "link": f"uploaded://{file.filename}",
        "text": text,
        "summary": text[:500],
        "source": "user_upload",
        "published": "",
    }
    vector_store.upsert_paper(paper, session_id)

    chunk_count = max(len(text.split()) // 500, 1)
    return UploadResponse(filename=file.filename, chunks_indexed=chunk_count, status="indexed")
