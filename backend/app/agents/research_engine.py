from __future__ import annotations

from dataclasses import dataclass
import re


_ACTION_WORDS = {
    "explain",
    "derive",
    "prove",
    "compare",
    "contrast",
    "analyze",
    "describe",
    "evaluate",
    "discuss",
    "show",
    "outline",
    "design",
    "implement",
    "estimate",
    "justify",
}

_STOP = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "in",
    "on",
    "for",
    "to",
    "with",
    "using",
    "also",
    "about",
    "into",
    "from",
    "that",
    "this",
    "these",
    "those",
}


@dataclass(frozen=True)
class ResearchNeed:
    need_id: str
    text: str
    kind: str
    priority: float


def _norm(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9\s+\-_/]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text: str) -> list[str]:
    return [t for t in _norm(text).split() if len(t) > 2 and t not in _STOP]


def title_signature(title: str) -> str:
    title = _norm(title)
    title = re.sub(r"\b(a|an|the)\b", " ", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title


def candidate_fingerprint(paper: dict) -> str:
    source = (paper.get("source") or "").lower().strip()
    arxiv_id = (paper.get("arxiv_id") or "").strip().lower()
    openalex_id = (paper.get("openalex_id") or "").strip().lower()
    doi = (paper.get("doi") or "").strip().lower()
    title = title_signature(paper.get("title", ""))

    if doi:
        return f"doi:{doi}"
    if arxiv_id:
        return f"arxiv:{arxiv_id}"
    if openalex_id:
        return f"openalex:{openalex_id}"
    if title:
        return f"title:{title}"
    return f"fallback:{source}:{paper.get('link', '')}"


def derive_research_needs(query: str, understanding: dict | None = None, plan: dict | None = None) -> list[ResearchNeed]:
    understanding = understanding or {}
    plan = plan or {}

    needs: list[ResearchNeed] = []

    main_topic = (understanding.get("main_topic") or "").strip()
    if main_topic:
        needs.append(ResearchNeed("core_topic", main_topic, "core", 1.0))

    for i, item in enumerate((understanding.get("objectives") or [])[:8]):
        text = str(item).strip()
        if text:
            needs.append(ResearchNeed(f"objective_{i}", text, "explicit_task", 0.95))

    for i, item in enumerate((understanding.get("subtopics") or [])[:10]):
        text = str(item).strip()
        if text:
            needs.append(ResearchNeed(f"subtopic_{i}", text, "subtopic", 0.8))

    for i, item in enumerate((understanding.get("methods_techniques") or [])[:8]):
        text = str(item).strip()
        if text:
            needs.append(ResearchNeed(f"method_{i}", text, "mechanism", 0.86))

    for i, item in enumerate((understanding.get("entities") or [])[:8]):
        text = str(item).strip()
        if text:
            needs.append(ResearchNeed(f"entity_{i}", text, "entity", 0.72))

    for i, item in enumerate((plan.get("information_needs") or [])[:12]):
        text = str(item).strip()
        if text:
            needs.append(ResearchNeed(f"plan_{i}", text, "information_need", 0.84))

    clauses = [c.strip() for c in re.split(r"[.?!;]+", query or "") if c.strip()]
    for i, c in enumerate(clauses[:8]):
        c_norm = _norm(c)
        if not c_norm:
            continue
        if any(w in c_norm.split() for w in _ACTION_WORDS):
            needs.append(ResearchNeed(f"clause_{i}", c, "query_clause", 0.9))

    dedup: dict[str, ResearchNeed] = {}
    for n in needs:
        key = _norm(n.text)
        if not key:
            continue
        prev = dedup.get(key)
        if prev is None or n.priority > prev.priority:
            dedup[key] = n

    return sorted(dedup.values(), key=lambda x: x.priority, reverse=True)


def need_overlap_score(need_text: str, text: str) -> float:
    a = set(_tokens(need_text))
    b = set(_tokens(text))
    if not a or not b:
        return 0.0
    inter = len(a.intersection(b))
    return inter / max(len(a), 1)


def assess_coverage(needs: list[ResearchNeed], papers: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for need in needs:
        best_score = 0.0
        evidence_ids: list[int] = []

        for idx, p in enumerate(papers):
            text = " ".join(
                [
                    p.get("title", ""),
                    p.get("summary", "")[:1200],
                    " ".join(p.get("keywords") or [])[:300],
                ]
            )
            overlap = need_overlap_score(need.text, text)
            rel = float(
                p.get("_relevance_orig")
                or p.get("_initial_sim")
                or p.get("final_score")
                or 0.0
            )
            score = 0.7 * overlap + 0.3 * min(max(rel, 0.0), 1.0)

            if score > best_score:
                best_score = score

            if score >= 0.33:
                evidence_ids.append(idx)

        if best_score >= 0.56:
            status = "covered"
        elif best_score >= 0.30:
            status = "partially_covered"
        else:
            status = "unsupported"

        out[need.need_id] = {
            "need": need.text,
            "kind": need.kind,
            "priority": need.priority,
            "status": status,
            "score": round(best_score, 3),
            "evidence_ids": evidence_ids[:6],
        }

    return out


def uncovered_needs(coverage: dict[str, dict], max_items: int = 4) -> list[str]:
    pending = [
        v for v in coverage.values()
        if v.get("status") in ("unsupported", "partially_covered")
    ]
    pending.sort(key=lambda x: (x.get("status") == "partially_covered", -float(x.get("priority", 0))))
    return [str(v.get("need", "")).strip() for v in pending if str(v.get("need", "")).strip()][:max_items]

def _content_signature(paper: dict) -> str:
    """
    Provider-independent identity key: normalized title + first author.

    candidate_fingerprint() keys on provider IDs, so the same work from
    two providers survives pass-1 dedup as two records — which is exactly
    what collides inside the embedding cache (addressed by
    title+first-author) and crashes the vector store. Year is excluded
    on purpose: the same canonical work legitimately carries different
    years across providers (preprint vs published vs mis-dated mirrors),
    and the best-evidenced copy should absorb the others.
    """
    title = title_signature(paper.get("title", ""))
    if not title:
        return ""
    authors = paper.get("authors") or []
    first = re.sub(r"[^a-z]", "", str(authors[0]).lower()) if authors else ""
    return f"{title}|{first}"


def _merge_pair(existing: dict, p: dict) -> None:
    """Fold paper `p` into `existing`, keeping the richer value per field."""
    if len((p.get("summary") or "")) > len((existing.get("summary") or "")):
        existing["summary"] = p.get("summary")
    if (p.get("citation_count") or 0) > (existing.get("citation_count") or 0):
        existing["citation_count"] = p.get("citation_count")
    for key in ("doi", "arxiv_id", "openalex_id", "venue", "published", "pdf_url"):
        if not existing.get(key) and p.get(key):
            existing[key] = p.get(key)
    for key in (
        "_primary_candidate",
        "_source_search_type",
        "_source_role",
        "_foundational_candidate",
        "_retrieval_purpose",
        "_source_term",
    ):
        if p.get(key) and not existing.get(key):
            existing[key] = p.get(key)
    if int(p.get("_convergence_hits") or 0) > int(
        existing.get("_convergence_hits") or 0
    ):
        existing["_convergence_hits"] = p["_convergence_hits"]
    if int(p.get("influential_citation_count") or 0) > int(
        existing.get("influential_citation_count") or 0
    ):
        existing["influential_citation_count"] = p["influential_citation_count"]
        
    existing_sources = set((existing.get("source") or "").split("+"))
    new_source = p.get("source") or ""
    if new_source:
        existing_sources.add(new_source)
    existing["source"] = (
        "+".join(sorted(s for s in existing_sources if s))
        or existing.get("source")
    )

_UPLOAD_SOURCE_LABELS = {
    "user_upload",
    "uploaded",
    "upload",
    "user_uploaded",
}


def merge_duplicate_papers(papers: list[dict]) -> list[dict]:
    uploaded = [
        p for p in papers
        if str(p.get("source") or "").lower() in _UPLOAD_SOURCE_LABELS
    ]
    mergeable = [
        p for p in papers
        if str(p.get("source") or "").lower() not in _UPLOAD_SOURCE_LABELS
    ]

    merged: dict[str, dict] = {}
    for p in mergeable:
        fp = candidate_fingerprint(p)
        existing = merged.get(fp)
        if not existing:
            merged[fp] = dict(p)
            continue
        _merge_pair(existing, p)

    records = list(merged.values())
    by_content: dict[str, list[dict]] = {}
    for p in records:
        key = _content_signature(p)
        if key:
            by_content.setdefault(key, []).append(p)

    absorbed: set[int] = set()
    for group in by_content.values():
        if len(group) < 2:
            continue
        group.sort(
            key=lambda p: (
                p.get("citation_count") or 0,
                bool(p.get("doi")),
                bool(p.get("arxiv_id")),
                bool(p.get("openalex_id")),
                len(p.get("summary") or ""),
            ),
            reverse=True,
        )
        base = group[0]
        for other in group[1:]:
            _merge_pair(base, other)
            absorbed.add(id(other))

    merged_literature = [p for p in records if id(p) not in absorbed]

    return merged_literature + uploaded