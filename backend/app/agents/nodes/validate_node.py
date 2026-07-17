import re
from datetime import datetime

from app.agents.state import AgentState

_SOFT_PENALTY = 0.85


def _validate_arxiv_metadata(paper: dict) -> dict:
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
    diff = abs(id_ym - pub_ym)

    if diff > 1:
        paper["_validation"] = f"MISMATCH: id implies {id_year}-{id_month:02d}, published={paper['published']} (diff={diff}mo)"
        paper["_validation_severity"] = "high" if diff > 24 else "low"
    else:
        paper["_validation"] = "ok"
        paper["_validation_severity"] = "none"

    return paper


def validate_node(state: AgentState) -> AgentState:
    validated = []
    flags = []
    dropped_count = 0

    for p in state["raw_search_results"]:
        p = _validate_arxiv_metadata(p)
        validation = p.get("_validation", "")

        if validation == "unparseable_date":
            flags.append(f"{p.get('title', '?')}: {validation}")
            dropped_count += 1
            continue

        if validation.startswith("MISMATCH") and p.get("_validation_severity") == "high":
            flags.append(f"{p.get('title', '?')}: {validation}")
            dropped_count += 1
            continue

        if validation.startswith("MISMATCH"):
            p["_validation_penalty"] = _SOFT_PENALTY
            flags.append(f"[soft] {p.get('title', '?')}: {validation}")

        validated.append(p)

    if dropped_count:
        print(f"[validate] dropped {dropped_count} paper(s) for unrecoverable metadata issues "
              f"(kept {len(validated)}/{len(state['raw_search_results'])})")

    return {
        **state,
        "raw_search_results": validated,
        "validation_results": flags,
    }