import re


def build_references(papers: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    order: list[str] = []
    for p in papers:
        link = p.get("link", "")
        if not link or link in seen:
            continue
        seen[link] = p
        order.append(link)
    refs = []
    for i, link in enumerate(order, start=1):
        p = seen[link]
        refs.append(
            {
                "id": i,
                "title": p.get("title", "Untitled"),
                "authors": p.get("authors", []) or [],
                "link": link,
                "published": p.get("published"),
                "source": p.get("source", "unknown"),
                "source_role": p.get("_source_role") or p.get("source_role"),
                "why_cited": p.get("_why_cited") or p.get("why_cited"),
                "support_level": p.get("_support_level") or p.get("support_level"),
            }
        )
    return refs


def filter_cited_references(references: list[dict], cited_links: list[str]) -> list[dict]:
    if not cited_links:
        return references
    cited_set = set(cited_links)
    filtered = [r for r in references if r["link"] in cited_set]
    for i, r in enumerate(filtered, start=1):
        r["id"] = i
    return filtered


def paper_id_to_ref_id_map(papers: list[dict], references: list[dict]) -> dict[str, int]:
    """
    Maps paper index (0-based, from [paper_id=N]) to reference id (1-based).
    Joins on link, NOT on positional index, so it is correct regardless of
    deduplication or reordering in build_references.
    """
    link_to_ref_id = {r["link"]: r["id"] for r in references}
    mapping = {}
    for i, p in enumerate(papers):
        link = p.get("link", "")
        if link in link_to_ref_id:
            mapping[str(i)] = link_to_ref_id[link]
    return mapping

_PAPER_ID_MARKER = re.compile(
    r"[\[【]\s*paper[\s_]?id\s*[=＝]\s*(\d+)\s*[\]】]",
    re.IGNORECASE,
)
_REF_ID_MARKER = re.compile(r"\[(\d+)\]")

def extract_paper_ids(text: str) -> list[str]:
    if not text:
        return []
    return _PAPER_ID_MARKER.findall(text)


def extract_ref_ids(text: str) -> list[int]:
    if not text:
        return []
    return [int(x) for x in _REF_ID_MARKER.findall(text)]


def rewrite_inline_citations(text: str, id_map: dict[str, int]) -> str:
    def _sub(m):
        pid = m.group(1)
        ref_id = id_map.get(pid)
        return f"[{ref_id}]" if ref_id is not None else ""
    text = _PAPER_ID_MARKER.sub(_sub, text)
    text = _PAPER_ID_MARKER.sub("", text)
    return text


def _clean_content(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(
        r"\[paper_id=\d+(?:\s*,\s*paper_id=\d+)+\]",
        lambda m: "".join(f"[paper_id={i}]" for i in re.findall(r"\d+", m.group(0))),
        text,
    )
    return text.strip()


def format_reference_block(references: list[dict]) -> str:
    lines = []
    for r in references:
        authors = ", ".join(r.get("authors", [])[:3])
        if len(r.get("authors", [])) > 3:
            authors += " et al."
        year = f" ({r['published']})" if r.get("published") else ""
        author_part = f"{authors}{year}. " if authors else ""
        lines.append(f"[{r['id']}] {author_part}{r['title']}. {r['link']}")
    return "\n".join(lines)