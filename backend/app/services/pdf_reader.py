import fitz
import httpx
import io
import hashlib
import json
import time
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parent.parent / "db" / "pdf_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

MIN_TEXT_LENGTH_THRESHOLD = 200
MIN_WORDS_PER_PAGE = 80
MAX_FRONT_CONTENT_PAGES = 10
MAX_FRONT_SCAN_LIMIT = 20
MAX_BACK_PAGES = 3
MAX_PDF_SIZE = 20_000_000


def _hash_url(pdf_url: str) -> str:
    return hashlib.sha256(pdf_url.encode()).hexdigest()

def _get_cache(pdf_url: str) -> dict | None:
    f = CACHE_DIR / f"{_hash_url(pdf_url)}.json"
    return json.loads(f.read_text()) if f.exists() else None

def _save_cache(pdf_url: str, result: dict):
    f = CACHE_DIR / f"{_hash_url(pdf_url)}.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(result))


def _ocr_page(page) -> str:
    pix = page.get_pixmap(dpi=150)
    from PIL import Image
    import pytesseract
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    return pytesseract.image_to_string(img)


def _extract_front_pages_ocr(doc) -> tuple[list[str], int]:
    front_pages = []
    scanned = 0
    total = len(doc)
    for i in range(min(total, MAX_FRONT_SCAN_LIMIT)):
        if len(front_pages) >= MAX_FRONT_CONTENT_PAGES:
            break
        text = _ocr_page(doc[i])
        scanned += 1
        if len(text.split()) >= MIN_WORDS_PER_PAGE:
            front_pages.append(text)
    return front_pages, scanned


def _extract_with_ocr(pdf_bytes: bytes) -> str:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    front_pages, scanned = _extract_front_pages_ocr(doc)
    total = len(doc)
    back_start = max(scanned, total - MAX_BACK_PAGES)
    back_pages = [_ocr_page(doc[i]) for i in range(back_start, total)]
    doc.close()
    return "\n".join(front_pages + back_pages)


def download_and_extract(pdf_url: str) -> dict:
    t0 = time.time()
    cached = _get_cache(pdf_url)
    if cached:
        print(f"[pdf_timing] {pdf_url[:60]} | CACHED")
        return cached

    try:
        resp = httpx.get(pdf_url, timeout=15, follow_redirects=True)
        if resp.status_code != 200:
            print(f"[pdf_timing] {pdf_url[:60]} | FAILED (status={resp.status_code})")
            return {"text": "", "extraction_method": "failed", "char_count": 0}
        if len(resp.content) > MAX_PDF_SIZE:
            print(f"[pdf_timing] {pdf_url[:60]} | FAILED (too large: {len(resp.content)/1e6:.1f}MB)")
            return {"text": "", "extraction_method": "failed", "char_count": 0}
        pdf_bytes = resp.content
    except (httpx.TimeoutException, httpx.HTTPError):
        print(f"[pdf_timing] {pdf_url[:60]} | FAILED (network exception)")
        return {"text": "", "extraction_method": "failed", "char_count": 0}

    t_download = time.time()

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except (fitz.FileDataError, RuntimeError, ValueError, Exception):
        print(f"[pdf_timing] {pdf_url[:60]} | FAILED (invalid pdf stream)")
        return {"text": "", "extraction_method": "failed", "char_count": 0}

    pages_text = [p.get_text() for p in doc]
    text = "\n".join(pages_text).strip()
    method = "pymupdf"

    if len(text) < MIN_TEXT_LENGTH_THRESHOLD:
        doc.close()
        try:
            text = _extract_with_ocr(pdf_bytes)
        except Exception:
            print(f"[pdf_timing] {pdf_url[:60]} | FAILED (ocr)")
            return {"text": "", "extraction_method": "failed", "char_count": 0}
        method = "ocr_fallback"
    else:
        doc.close()

    t_extract = time.time()

    result = {"text": text, "extraction_method": method, "char_count": len(text)}
    print(f"[pdf_timing] {pdf_url[:60]} | method={method} | download={round(t_download-t0,2)}s | extract={round(t_extract-t_download,2)}s")
    _save_cache(pdf_url, result)
    return result


async def extract_all(pdf_urls: list[str]) -> list[dict]:
    import asyncio

    loop = asyncio.get_event_loop()
    tasks = [loop.run_in_executor(None, download_and_extract, url) for url in pdf_urls]
    extracted = await asyncio.gather(*tasks)

    return [{"url": url, **result} for url, result in zip(pdf_urls, extracted)]
