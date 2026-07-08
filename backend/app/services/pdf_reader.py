import fitz
import httpx
import io
import hashlib
import json
from pathlib import Path
from app.agents.schemas import PageClassification

CACHE_DIR = Path("app/db/pdf_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

MIN_TEXT_LENGTH_THRESHOLD = 200
MIN_WORDS_PER_PAGE = 80
MAX_FRONT_CONTENT_PAGES = 10
MAX_FRONT_SCAN_LIMIT = 20
BACK_SCAN_LIMIT = 15
MAX_PDF_SIZE = 20_000_000


def _hash_url(pdf_url: str) -> str:
    return hashlib.sha256(pdf_url.encode()).hexdigest()

def _get_cache(pdf_url: str) -> dict | None:
    f = CACHE_DIR / f"{_hash_url(pdf_url)}.json"
    return json.loads(f.read_text()) if f.exists() else None

def _save_cache(pdf_url: str, result: dict):
    f = CACHE_DIR / f"{_hash_url(pdf_url)}.json"
    f.write_text(json.dumps(result))


def _extract_with_pymupdf(pdf_bytes: bytes) -> str:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text = "\n".join(page.get_text() for page in doc)
    doc.close()
    return text.strip()


def _detect_headings(doc) -> list[dict]:
    headings = []
    body_sizes = []

    for page in doc:
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    body_sizes.append(round(span["size"]))

    if not body_sizes:
        return []
    baseline = max(set(body_sizes), key=body_sizes.count)

    for page_num, page in enumerate(doc):
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                line_text = "".join(s["text"] for s in line["spans"]).strip()
                if not line_text or len(line_text) > 60:
                    continue
                max_size = max(s["size"] for s in line["spans"])
                is_bold = any("bold" in s["font"].lower() for s in line["spans"])
                if max_size > baseline + 1.5 or is_bold:
                    headings.append({"page": page_num, "text": line_text})
    return headings


CONCLUSION_KEYWORDS = ("conclusion", "discussion", "future work", "summary", "concluding remarks")
REFERENCE_KEYWORDS = ("references", "bibliography")

def _trim_to_conclusion_pymupdf(doc, full_text_by_page: list[str]) -> str:
    headings = _detect_headings(doc)
    conclusion_page = None
    reference_page = None

    for h in headings:
        low = h["text"].lower()
        if conclusion_page is None and any(k in low for k in CONCLUSION_KEYWORDS):
            conclusion_page = h["page"]
        elif conclusion_page is not None and any(k in low for k in REFERENCE_KEYWORDS):
            reference_page = h["page"]
            break

    if conclusion_page is None:
        return ""

    end = reference_page if reference_page else len(full_text_by_page)
    return "\n".join(full_text_by_page[conclusion_page:end])


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


def _classify_page_llm(llm, page_text: str) -> PageClassification:
    structured_llm = llm.with_structured_output(PageClassification)
    prompt = (
        "Classify which section of an academic paper this page most likely belongs to. "
        f"Page content:\n\n{page_text[:1500]}"
    )
    return structured_llm.invoke(prompt)


def _extract_conclusion_ocr(doc, scan_start: int, llm) -> str:
    total = len(doc)
    start = max(scan_start, total - BACK_SCAN_LIMIT)
    kept = []
    hit_conclusion = False

    for i in range(start, total):
        text = _ocr_page(doc[i])
        try:
            result = _classify_page_llm(llm, text)
        except Exception:
            continue

        if result.section_type == "conclusion":
            hit_conclusion = True
            kept.append(text)
        elif result.section_type == "references" and hit_conclusion:
            break
        elif result.section_type == "references" and not hit_conclusion:
            break

    return "\n".join(kept)


def _extract_with_ocr(pdf_bytes: bytes, llm=None) -> str:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    front_pages, scanned = _extract_front_pages_ocr(doc)

    conclusion_text = ""
    if llm is not None:
        try:
            conclusion_text = _extract_conclusion_ocr(doc, scanned, llm)
        except Exception:
            conclusion_text = ""

    doc.close()
    return "\n".join(front_pages) + ("\n" + conclusion_text if conclusion_text else "")


def download_and_extract(pdf_url: str, llm=None) -> dict:
    cached = _get_cache(pdf_url)
    if cached:
        return cached

    try:
        resp = httpx.get(pdf_url, timeout=15, follow_redirects=True)
        if resp.status_code != 200 or len(resp.content) > MAX_PDF_SIZE:
            return {"text": "", "extraction_method": "failed", "char_count": 0}
        pdf_bytes = resp.content
    except (httpx.TimeoutException, httpx.HTTPError):
        return {"text": "", "extraction_method": "failed", "char_count": 0}

    text = _extract_with_pymupdf(pdf_bytes)
    method = "pymupdf"

    if len(text) < MIN_TEXT_LENGTH_THRESHOLD:
        text = _extract_with_ocr(pdf_bytes, llm=llm)
        method = "ocr_fallback"
    else:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pages_text = [p.get_text() for p in doc]
        conclusion_only = _trim_to_conclusion_pymupdf(doc, pages_text)
        doc.close()
        if conclusion_only:
            text = text[:3000] + "\n...\n" + conclusion_only

    result = {"text": text, "extraction_method": method, "char_count": len(text)}
    _save_cache(pdf_url, result)
    return result


async def extract_all(pdf_urls: list[str], llm=None) -> list[dict]:
    import asyncio

    results = []
    to_fetch = []
    for url in pdf_urls:
        cached = _get_cache(url)
        if cached:
            results.append({"url": url, **cached})
        else:
            to_fetch.append(url)

    if to_fetch:
        loop = asyncio.get_event_loop()
        tasks = [loop.run_in_executor(None, download_and_extract, url, llm) for url in to_fetch]
        extracted = await asyncio.gather(*tasks)
        for url, result in zip(to_fetch, extracted):
            results.append({"url": url, **result})

    return results
