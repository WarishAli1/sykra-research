import re


def _authors_apa(authors: list[str]) -> str:
    if not authors:
        return "Unknown Author"
    if len(authors) <= 3:
        return ", ".join(authors)
    return f"{authors[0]} et al."


def _authors_ieee(authors: list[str]) -> str:
    def initials(name: str) -> str:
        parts = name.strip().split()
        if len(parts) < 2:
            return name
        return f"{parts[0][0]}. {parts[-1]}"
    if not authors:
        return "Unknown Author"
    formatted = [initials(a) for a in authors[:3]]
    if len(authors) > 3:
        formatted.append("et al.")
    return ", ".join(formatted)


def _bibtex_key(paper: dict) -> str:
    first_author = paper.get("authors", ["unknown"])[0].split()[-1].lower() if paper.get("authors") else "unknown"
    year = str(paper.get("published", "n.d."))[:4]
    title_word = re.sub(r"[^a-zA-Z]", "", paper["title"].split()[0]).lower()
    return f"{first_author}{year}{title_word}"


SOURCE_LABELS = {"arxiv": "arXiv", "openalex": "OpenAlex", "user_upload": "User Upload"}


def format_apa(paper: dict) -> str:
    authors = _authors_apa(paper.get("authors", []))
    year = str(paper.get("published", "n.d."))[:4]
    label = SOURCE_LABELS.get(paper.get("source", ""), "Web")
    return f"{authors} ({year}). {paper['title']}. {label}. {paper['link']}"


def format_ieee(paper: dict, index: int = 1) -> str:
    authors = _authors_ieee(paper.get("authors", []))
    year = str(paper.get("published", "n.d."))[:4]
    return f'[{index}] {authors}, "{paper["title"]}," {year}. [Online]. Available: {paper["link"]}'


def format_bibtex(paper: dict) -> str:
    key = _bibtex_key(paper)
    authors_bib = " and ".join(paper.get("authors", ["Unknown"]))
    year = str(paper.get("published", "n.d."))[:4]
    return (
        f"@article{{{key},\n"
        f"  title={{{paper['title']}}},\n"
        f"  author={{{authors_bib}}},\n"
        f"  year={{{year}}},\n"
        f"  url={{{paper['link']}}}\n"
        f"}}"
    )


def format_citations(papers: list[dict], style: str = "apa") -> list[str]:
    if style == "ieee":
        return [format_ieee(p, i + 1) for i, p in enumerate(papers)]
    if style == "bibtex":
        return [format_bibtex(p) for p in papers]
    return [format_apa(p) for p in papers]
