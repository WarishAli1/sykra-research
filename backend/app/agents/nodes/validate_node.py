import re
from datetime import datetime

from app.agents.state import AgentState


def validate_arxiv_metadata(paper: dict) -> dict:
    match = re.search(r'(\d{2})(\d{2})\.\d{4,5}', paper.get("link", ""))
    if not match:
        paper["_validation"] = "no_arxiv_id_found"
        return paper

    id_year, id_month = int(match.group(1)) + 2000, int(match.group(2))
    try:
        pub_date = datetime.strptime(paper["published"], "%Y-%m-%d")
    except (ValueError, KeyError):
        try:
            pub_date = datetime.strptime(paper["published"], "%Y")
        except (ValueError, KeyError):
            paper["_validation"] = "unparseable_date"
            return paper

    id_ym = id_year * 12 + id_month
    pub_ym = pub_date.year * 12 + pub_date.month
    if abs(id_ym - pub_ym) > 1:
        paper["_validation"] = f"MISMATCH: id implies {id_year}-{id_month:02d}, published={paper['published']}"
    else:
        paper["_validation"] = "ok"
    return paper


def validate_node(state: AgentState) -> AgentState:
    validated = []
    flags = []
    for p in state["raw_search_results"]:
        if p.get("source") == "seminal_lookup":
            p["_validation"] = "trusted_source"
            validated.append(p)
            continue
        p = validate_arxiv_metadata(p)
        if p.get("_validation", "").startswith("MISMATCH") or p.get("_validation") == "unparseable_date":
            flags.append(f"{p.get('title', '?')}: {p['_validation']}")
            continue
        validated.append(p)

    return {
        **state,
        "raw_search_results": validated,
        "validation_results": flags,
    }
