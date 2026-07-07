import hashlib
import json
import asyncio
from pathlib import Path

import fitz
import httpx
import io

CACHE_DIR = Path("app/db/pdf_cache")
MIN_TEXT_LENGTH_THRESHOLD = 200

def _hash_url(pdf_url: str) -> str:
    return hashlib.sha256(pdf_url.encode()).hexdigest()

def get_cached_extraction(pdf_url: str) -> dict | None:
    cache_file = CACHE_DIR / f"{_hash_url(pdf_url)}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text())
    return None

def save_cached_extraction(pdf_url: str, result: dict):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{_hash_url(pdf_url)}.json"
    cache_file.write_text(json.dumps(result))

def extract_with_pymupdf(pdf_bytes: bytes) -> str:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text = "\n".join(page.get_text() for page in doc)
    doc.close()
    return text.strip()

def extract_with_ocr(pdf_bytes: bytes) -> str:
    from PIL import Image
    import pytesseract
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    full_text = []
    for page in doc:
        pix = page.get_pixmap(dpi=300)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        page_text = pytesseract.image_to_string(img)
        full_text.append(page_text)
    doc.close()
    return "\n".join(full_text).strip()

def download_and_extract(pdf_url: str) -> dict:
    cached = get_cached_extraction(pdf_url)
    if cached:
        return cached

    resp = httpx.get(pdf_url, timeout=30, follow_redirects=True)
    pdf_bytes = resp.content

    text = extract_with_pymupdf(pdf_bytes)
    method_used = "pymupdf"

    if len(text) < MIN_TEXT_LENGTH_THRESHOLD:
        text = extract_with_ocr(pdf_bytes)
        method_used = "ocr_fallback"

    result = {"text": text, "extraction_method": method_used, "char_count": len(text)}
    save_cached_extraction(pdf_url, result)
    return result

async def _download(client: httpx.AsyncClient, pdf_url: str) -> bytes | None:
    try:
        resp = await client.get(pdf_url, timeout=15, follow_redirects=True)
        if resp.status_code != 200 or len(resp.content) > 20_000_000:
            return None
        return resp.content
    except (httpx.TimeoutException, httpx.HTTPError):
        return None

async def extract_all(pdf_urls: list[str]) -> list[dict]:
    results = []
    async with httpx.AsyncClient() as client:
        to_fetch = []
        for url in pdf_urls:
            cached = get_cached_extraction(url)
            if cached:
                results.append(cached)
            else:
                to_fetch.append(url)

        if to_fetch:
            downloaded = await asyncio.gather(*[_download(client, u) for u in to_fetch])
            for url, pdf_bytes in zip(to_fetch, downloaded):
                if pdf_bytes is None:
                    continue
                text = extract_with_pymupdf(pdf_bytes)
                method = "pymupdf"
                if len(text) < MIN_TEXT_LENGTH_THRESHOLD:
                    text = extract_with_ocr(pdf_bytes)
                    method = "ocr_fallback"
                result = {"text": text, "extraction_method": method, "char_count": len(text)}
                save_cached_extraction(url, result)
                results.append(result)

    return results
