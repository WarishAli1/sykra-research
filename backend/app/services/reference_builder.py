import re


def build_references(papers: list[dict]) -> list[dict]:
    """papers: list of paper dicts as stored in ranked_papers / uploaded metadata.
    Returns a list of {id, title, authors, link, published, source} with 1-based ids
    in the same order as `papers` (dedup by link, stable order of first appearance).
    """
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
        refs.append({
            "id": i,
            "title": p.get("title", "Untitled"),
            "authors": p.get("authors", []) or [],
            "link": link,
            "published": p.get("published"),
            "source": p.get("source", "unknown"),
        })
    return refs


def paper_id_to_ref_id_map(papers: list[dict], references: list[dict]) -> dict[str, int]:
    """Maps the internal 0-based `paper_id=N` index (position in `papers`) to the
    1-based reference id used in the final answer text, via link matching."""
    link_to_ref_id = {r["link"]: r["id"] for r in references}
    mapping = {}
    for i, p in enumerate(papers):
        link = p.get("link", "")
        if link in link_to_ref_id:
            mapping[str(i)] = link_to_ref_id[link]
    return mapping


_PAPER_ID_MARKER = re.compile(r"\[paper_id=(\d+)\]")


def rewrite_inline_citations(text: str, id_map: dict[str, int]) -> str:
    """Rewrites any leftover [paper_id=N] markers into user-facing [n] markers.
    Safe no-op if the text has none (current prompts already strip them, but this
    guards against a model regression re-introducing them, and is what researched
    mode relies on since it explicitly asks for inline citations)."""
    def _sub(m):
        pid = m.group(1)
        ref_id = id_map.get(pid)
        return f"[{ref_id}]" if ref_id is not None else ""
    return _PAPER_ID_MARKER.sub(_sub, text)


def format_reference_block(references: list[dict]) -> str:
    """Human-readable numbered reference list, e.g. for appending to researched-mode
    answers and for the PDF export."""
    lines = []
    for r in references:
        authors = ", ".join(r["authors"][:3])
        if len(r["authors"]) > 3:
            authors += " et al."
        year = f" ({r['published']})" if r.get("published") else ""
        author_part = f"{authors}{year}. " if authors else ""
        lines.append(f"[{r['id']}] {author_part}{r['title']}. {r['link']}")
    return "\n".join(lines)