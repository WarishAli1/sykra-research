import os
import re

import fitz
from PIL import Image
import pytesseract
from fastapi import APIRouter, UploadFile, File, HTTPException

from app.models.schemas import UploadResponse
from app.services.vector_store import vector_store
from app.services.graph_store import graph_store

router = APIRouter()
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

_SCANNED_PAGE_CHAR_THRESHOLD = 50
_DPI = 150


def _is_scanned_page(text: str) -> bool:
    return len(text.strip()) < _SCANNED_PAGE_CHAR_THRESHOLD


def _clean_text(text: str) -> str:
    text = text.replace("\x0c", "\n")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[^\S\n]+", " ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return text.strip()


def _render_page_to_pil(page: fitz.Page, dpi: int) -> Image.Image:
    pix = page.get_pixmap(dpi=dpi, alpha=False)
    return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)


def _ocr_page(page: fitz.Page, dpi: int = _DPI) -> str:
    try:
        img = _render_page_to_pil(page, dpi)
        return pytesseract.image_to_string(img)
    except Exception as e:
        print(f"[upload] OCR failed: {e}")
        return ""


def extract_text_from_pdf(content: bytes) -> dict:
    try:
        doc = fitz.open(stream=content, filetype="pdf")
    except Exception as exc:
        raise RuntimeError(f"Could not open PDF: {exc}") from exc

    page_texts = []
    ocr_pages = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text("text")

        if _is_scanned_page(text):
            print(f"[upload] Page {page_num + 1} appears scanned – running OCR")
            text = _ocr_page(page)
            if text.strip():
                ocr_pages.append(page_num + 1)

        if text.strip():
            page_texts.append(f"\n\n[PAGE {page_num + 1}]\n\n{text}")

    doc.close()

    full_text = _clean_text("\n".join(page_texts))

    return {
        "text": full_text,
        "page_count": len(page_texts),
        "ocr_pages": ocr_pages,
        "ocr_used": len(ocr_pages) > 0,
    }


@router.post("/upload", response_model=UploadResponse)
async def upload_pdf(file: UploadFile = File(...), session_id: str = "default"):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    print(f"[upload] Processing file: {file.filename} for session: {session_id}")

    content = await file.read()

    result = extract_text_from_pdf(content)
    text = result["text"]

    if not text.strip():
        raise HTTPException(
            status_code=400,
            detail="Could not extract text from PDF. The file may be corrupted or contain only images."
        )

    print(f"[upload] Extracted {len(text)} chars from {result['page_count']} pages (OCR used: {result['ocr_used']})")

    session_dir = os.path.join(UPLOAD_DIR, session_id)
    os.makedirs(session_dir, exist_ok=True)
    file_path = os.path.join(session_dir, file.filename)
    with open(file_path, "wb") as f:
        f.write(content)

    file_url = f"http://localhost:8000/api/uploads/{session_id}/{file.filename}"

    paper = {
        "title": file.filename,
        "link": file_url,
        "text": text,
        "summary": text[:500],
        "source": "user_upload",
        "published": "",
        "authors": [],
        "paper_type": "user_upload",
    }
    vector_store.upsert_paper(paper, session_id)
    graph_store.upsert_paper(paper, session_id)

    chunk_count = max(len(text.split()) // 500, 1)

    return UploadResponse(
        filename=file.filename,
        chunks_indexed=chunk_count,
        status="indexed"
    )
