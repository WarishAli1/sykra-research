import os
import re
import asyncio
import fitz
from PIL import Image
import pytesseract
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from fastapi.responses import StreamingResponse
from app.services.sse import sse_event
from app.services import cancellation

from app.models.schemas import UploadResponse
from app.services.vector_store import vector_store
from app.services.graph_store import graph_store
from app.config import settings

router = APIRouter()
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

_SCANNED_PAGE_CHAR_THRESHOLD = 50
_DPI = 150

_BACKEND_PUBLIC_URL = getattr(settings, "BACKEND_PUBLIC_URL", "http://localhost:8000")


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


def _safe_filename(filename: str) -> str:
    base = os.path.basename(filename)
    return re.sub(r"[^\w\-. ]", "_", base)


@router.post("/upload", response_model=UploadResponse)
async def upload_pdf(file: UploadFile = File(...), session_id: str = "default"):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    safe_name = _safe_filename(file.filename)
    print(f"[upload] Processing file: {safe_name} for session: {session_id}")

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
    file_path = os.path.join(session_dir, safe_name)
    with open(file_path, "wb") as f:
        f.write(content)

    file_url = f"{_BACKEND_PUBLIC_URL}/api/uploads/{session_id}/{safe_name}"

    paper = {
        "title": safe_name,
        "link": file_url,
        "file_url": file_url,
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
        filename=safe_name,
        chunks_indexed=chunk_count,
        status="indexed",
        file_url=file_url,
        link=file_url,
    )


@router.get("/uploads/{session_id}/{filename}")
async def serve_uploaded_pdf(session_id: str, filename: str):
    """This route did not previously exist — file_url pointed at it but nothing
    served it, so 'open PDF' from the Library always 404'd. Path components are
    taken as-is from the URL; combined with _safe_filename() at write time, and
    os.path.basename() here, this blocks '../' traversal on read."""
    safe_session = os.path.basename(session_id)
    safe_name = os.path.basename(filename)
    file_path = os.path.join(UPLOAD_DIR, safe_session, safe_name)

    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found.")

    return FileResponse(file_path, media_type="application/pdf", filename=safe_name)

@router.delete("/uploads/{session_id}")
async def delete_uploaded_pdf(
    session_id: str,
    link: str,
):
    vector_store.delete_paper(link,session_id)
    graph_store.delete_paper(link)

    filename = os.path.basename(link)
    file_path = os.path.join(UPLOAD_DIR, session_id, filename)

    if os.path.exists(file_path):
        os.remove(file_path)

    return {"status": "deleted"}


_CANCEL_POLL_INTERVAL = 0.25
_CANCELLED = object()


async def _await_with_cancel_watch(task: "asyncio.Task", request_id: str, sentinel_ok: bool = False):
    """Await `task` while polling the cancellation registry every
    _CANCEL_POLL_INTERVAL seconds. If the request is cancelled before the
    task finishes, this returns None (or _CANCELLED if sentinel_ok) and
    leaves the underlying thread to finish on its own — Python threads can't
    be killed, but the client stops waiting on it immediately, which is what
    actually matters for the Stop button.
    """
    if not request_id:
        return await task

    while not task.done():
        if cancellation.is_cancelled(request_id):
            return _CANCELLED if sentinel_ok else None
        await asyncio.sleep(_CANCEL_POLL_INTERVAL)

    return task.result()


@router.post("/upload/stream")
async def upload_pdf_stream(file: UploadFile = File(...), session_id: str = "default", request_id: str = ""):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    safe_name = _safe_filename(file.filename)

    content = await file.read()

    async def event_stream():
        if request_id:
            cancellation.register(request_id)
        try:
            try:
                yield sse_event(
                    "progress",
                    stage="parsing",
                    label="Parsing PDF..."
                )
                await asyncio.sleep(0)

                if request_id and cancellation.is_cancelled(request_id):
                    yield sse_event("cancelled")
                    return

                yield sse_event("progress", stage="extracting", label="Extracting text...")
                await asyncio.sleep(0)
                extract_task = asyncio.create_task(
                    asyncio.to_thread(extract_text_from_pdf, content)
                )
                result = await _await_with_cancel_watch(extract_task, request_id)
                if result is None:
                    yield sse_event("cancelled")
                    return
                text = result["text"]

                if request_id and cancellation.is_cancelled(request_id):
                    yield sse_event("cancelled")
                    return

                if result["ocr_used"]:
                    yield sse_event(
                        "progress",
                        stage="ocr",
                        label=f"Running OCR on {len(result['ocr_pages'])} pages..."
                    )

                if not text.strip():
                    yield sse_event("error", message="Could not extract text from PDF.")
                    return

                if request_id and cancellation.is_cancelled(request_id):
                    yield sse_event("cancelled")
                    return

                yield sse_event(
                    "progress",
                    stage="saving",
                    label="Saving PDF..."
                )
                await asyncio.sleep(0)

                session_dir = os.path.join(UPLOAD_DIR, session_id)
                os.makedirs(session_dir, exist_ok=True)

                file_path = os.path.join(session_dir, safe_name)
                with open(file_path, "wb") as f:
                    f.write(content)

                file_url = f"{_BACKEND_PUBLIC_URL}/api/uploads/{session_id}/{safe_name}"

                paper = {
                    "title": safe_name,
                    "link": file_url,
                    "file_url": file_url,
                    "text": text,
                    "summary": text[:500],
                    "source": "user_upload",
                    "published": "",
                    "authors": [],
                    "paper_type": "user_upload",
                }

                if request_id and cancellation.is_cancelled(request_id):
                    yield sse_event("cancelled")
                    return

                yield sse_event(
                    "progress",
                    stage="embedding",
                    label="Generating embeddings..."
                )
                await asyncio.sleep(0)

                embed_task = asyncio.create_task(
                    asyncio.to_thread(vector_store.upsert_paper, paper, session_id)
                )
                embed_result = await _await_with_cancel_watch(embed_task, request_id, sentinel_ok=True)
                if embed_result is _CANCELLED:
                    yield sse_event("cancelled")
                    return

                if request_id and cancellation.is_cancelled(request_id):
                    yield sse_event("cancelled")
                    return

                yield sse_event(
                    "progress",
                    stage="graph",
                    label="Building knowledge graph..."
                )
                await asyncio.sleep(0)

                graph_task = asyncio.create_task(
                    asyncio.to_thread(graph_store.upsert_paper, paper, session_id)
                )
                graph_result = await _await_with_cancel_watch(graph_task, request_id, sentinel_ok=True)
                if graph_result is _CANCELLED:
                    yield sse_event("cancelled")
                    return

                yield sse_event("result", payload={
                    "filename": safe_name,
                    "file_url": file_url,
                    "link": file_url,
                    "status": "indexed",
                })
            except Exception as exc:
                print(f"[upload/stream] failed: {exc}")
                yield sse_event("error", message=f"Upload failed: {exc}")
        finally:
            if request_id:
                cancellation.cleanup(request_id)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/upload/cancel/{request_id}")
def upload_cancel(request_id: str):
    found = cancellation.cancel(request_id)
    if not found:
        return {"cancelled": False}
    return {"cancelled": True}