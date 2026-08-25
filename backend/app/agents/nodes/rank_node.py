import math
import re as _re
from datetime import datetime
from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage
from app.agents.research_engine import (
    assess_coverage,
    derive_research_needs,
    merge_duplicate_papers,
    need_overlap_score,
)
from app.agents.schemas import PaperJudgment
from app.agents.state import AgentState
from app.services.embeddings import embed_texts, similarity
from app.services.paper_search import fetch_openalex_citation_graph
from app.services.llm_client import get_llm, is_llm_rate_limited
from app.config import settings

CURRENT_YEAR = datetime.now().year
MIN_ABSTRACT_LENGTH = 40
PRE_FILTER_N = 48
SOURCE_ROLE_PRIMARY = "primary"
SOURCE_ROLE_SECONDARY = "secondary"
SOURCE_ROLE_SURVEY = "survey"
SOURCE_ROLE_BACKGROUND = "background"
SOURCE_ROLE_APPLICATION = "application"

def _coerce_float01(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        v = float(value)
    except Exception:
        return default
    return max(0.0, min(1.0, v))

def _normalize_str_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(x) for x in value if x is not None and str(x).strip()]
    return []

def _normalize_judgments(raw, candidate_count: int) -> dict[int, dict]:
    items = []
    if isinstance(raw, dict):
        if isinstance(raw.get("judgments"), list):
            items = raw["judgments"]
        elif isinstance(raw.get("papers"), list):
            items = raw["papers"]
        elif isinstance(raw.get("results"), list):
            items = raw["results"]
        elif isinstance(raw.get("items"), list):
            items = raw["items"]
        else:
            for k, v in raw.items():
                if isinstance(v, dict):
                    v = dict(v)
                    v.setdefault("paper_id", k)
                    items.append(v)
    elif isinstance(raw, list):
        items = raw

    out: dict[int, dict] = {}
    allowed_roles = {
        "primary", "secondary", "survey", "application", "background", "irrelevant",
    }

    for idx, item in enumerate(items[:candidate_count]):
        if not isinstance(item, dict):
            continue
        pid = item.get("paper_id", item.get("id", item.get("index", idx)))
        try:
            pid = int(pid)
        except Exception:
            pid = idx
        if pid < 0 or pid >= candidate_count:
            pid = idx

        answers_raw = next(
            (
                item[k]
                for k in (
                    "answers_question", "answer_relevance", "relevance",
                    "relevance_score", "question_relevance", "support_score",
                    "overall_score", "score", "fit",
                )
                if item.get(k) is not None
            ),
            None,
        )
        primary_raw = next(
            (
                item[k]
                for k in (
                    "primary_source_fit", "primary_fit", "primary_score",
                    "primary_source_score", "canonical_fit", "origin_fit",
                )
                if item.get(k) is not None
            ),
            None,
        )
        role = str(
            item.get("source_role") or item.get("role")
            or item.get("source_type") or "background"
        ).lower().strip()
        if role not in allowed_roles:
            role = "background"

        coverage = item.get(
            "requirement_coverage",
            item.get("requirements", item.get("requirement_ids", item.get("coverage", []))),
        )
        out[pid] = {
            "answers_question": _coerce_float01(answers_raw, 0.0),
            "primary_source_fit": _coerce_float01(primary_raw, 0.0),
            "source_role": role,
            "reason": str(item.get("reason") or "")[:500],
            "requirement_coverage": _normalize_str_list(coverage),
        }
    return out

class PaperJudgmentBatch(BaseModel):
    judgments: list[PaperJudgment] = Field(default_factory=list)

def _has_valid_abstract(paper: dict) -> bool:
    return len((paper.get("summary") or "").strip()) >= MIN_ABSTRACT_LENGTH

def _citation_score(citations: int) -> float:
    return math.log(1 + max(citations or 0, 0)) / math.log(1 + 100_000)

def _recency_score(published: str) -> float:
    try:
        year = int(str(published)[:4])
    except Exception:
        return 0.35
    age = max(CURRENT_YEAR - year, 0)
    return max(0.0, 1 - age / 15)

def _is_review(title: str) -> bool:
    t = (title or "").lower()
    return any(k in t for k in ("survey", "review", "systematic review", "meta-analysis", "overview"))

def _paper_type_bonus(paper: dict, needs: list) -> float:
    wants_overview = any("overview" in n.text.lower() or "background" in n.text.lower() for n in needs)
    is_review = _is_review(paper.get("title", ""))
    if is_review and wants_overview:
        return 0.08
    if is_review and not wants_overview:
        return -0.06
    return 0.04

def _source_authority_score(paper: dict) -> float:
    source = (paper.get("source") or "").lower()
    cites = paper.get("citation_count", 0) or 0
    base = _citation_score(cites)
    if "openalex" in source:
        return min(1.0, base + 0.08)
    if "arxiv" in source:
        return min(1.0, base + 0.04)
    if "web" in source:
        return min(1.0, base + 0.02)
    return base

def _query_alignment_score(paper: dict, query: str, needs: list) -> float:
    text = " ".join(
        [
            paper.get("title", ""),
            (paper.get("summary") or "")[:1600],
            " ".join(paper.get("keywords") or []),
        ]
    )
    base = need_overlap_score(query, text)
    if not needs:
        return base
    need_scores = [need_overlap_score(n.text, text) * n.priority for n in needs]
    if not need_scores:
        return base
    return 0.55 * base + 0.45 * (sum(need_scores) / max(sum(n.priority for n in needs), 1e-6))

def _primary_source_score(paper: dict, answer_spec: dict) -> float:
    if not answer_spec.get("primary_source_required"):
        return 0.0
    score = 0.0
    title = (paper.get("title") or "").lower()
    for entity in answer_spec.get("canonical_entities", []):
        expected = (entity.get("expected_primary_source") or "").lower()
        if expected and expected in title:
            score = max(score, 1.0)
        for alias in entity.get("aliases", []):
            if alias.lower() in title:
                score = max(score, 0.7)
    if paper.get("_primary_candidate"):
        score = max(score, 0.8)
    citations = paper.get("citation_count", 0) or 0
    if citations >= 10000:
        score += 0.15
    elif citations >= 2000:
        score += 0.10
    elif citations >= 500:
        score += 0.05
    return min(score, 1.0)

def _canonical_entity_score(paper: dict, answer_spec: dict) -> float:
    title = (paper.get("title") or "").lower()
    score = 0.0
    for entity in answer_spec.get("canonical_entities", []):
        names = [entity.get("name") or ""]
        names.extend(entity.get("aliases") or [])
        for name in names:
            name = name.strip().lower()
            if name and name in title:
                score = max(score, 0.8)
    return score

def _origin_year_score(paper: dict, answer_spec: dict) -> float:
    try:
        year = int(str(paper.get("published") or "")[:4])
    except (TypeError, ValueError):
        return 0.0
    score = 0.0
    for entity in answer_spec.get("canonical_entities", []):
        expected = entity.get("expected_year")
        if expected:
            diff = abs(year - expected)
            score = max(score, max(0.0, 1.0 - diff / 10))
    return score

def _survey_penalty(paper: dict, answer_spec: dict) -> float:
    title = (paper.get("title") or "").lower()
    is_survey = any(
        word in title
        for word in ("survey", "review", "overview", "comprehensive review")
    )
    if not is_survey:
        return 0.0
    question_types = answer_spec.get("question_types", [])
    if (
        answer_spec.get("primary_source_required")
        or "mathematical_derivation" in question_types
        or "technical_explanation" in question_types
    ):
        return 0.25
    return 0.0

def _requirement_match_score(
    paper: dict,
    requirement_texts: list[str],
    requirement_vecs: list[list[float]],
) -> float:
    paper_vec = paper.get("abstract_vec")
    if paper_vec is None or not requirement_vecs:
        return 0.0
    sims = [similarity(paper_vec, rv) for rv in requirement_vecs]
    return max(sims) if sims else 0.0

def _classify_source_role(paper: dict, answer_spec: dict) -> str:
    title = (paper.get("title") or "").lower()
    if answer_spec.get("primary_source_required"):
        if _primary_source_score(paper, answer_spec) >= 0.8:
            return SOURCE_ROLE_PRIMARY
        if paper.get("_primary_candidate"):
            return SOURCE_ROLE_PRIMARY
    if any(
        word in title
        for word in ("survey", "review", "overview", "comprehensive review")
    ):
        return SOURCE_ROLE_SURVEY
    rel = float(
        paper.get("_relevance_orig")
        or paper.get("_initial_sim")
        or paper.get("final_score")
        or 0.0
    )
    if rel < 0.30:
        return SOURCE_ROLE_BACKGROUND
    if not paper.get("_foundational_candidate") and not paper.get("_primary_candidate"):
        for entity in answer_spec.get("canonical_entities", []):
            name = (entity.get("name") or "").lower()
            if name and name in title:
                return SOURCE_ROLE_APPLICATION
    return SOURCE_ROLE_SECONDARY

def _answer_spec_weighted_score(
    paper: dict,
    orig_vec: list[float],
    other_vecs: list[list[float]],
    query: str,
    needs: list,
    answer_spec: dict,
    requirement_texts: list[str],
    requirement_vecs: list[list[float]],
    is_canonical: bool,
) -> float:
    vec = paper.get("abstract_vec")
    if vec is None:
        return 0.0

    rel_orig = similarity(orig_vec, vec)
    rel_other = max((similarity(v, vec) for v in other_vecs), default=0.0)
    semantic = 0.65 * rel_orig + 0.35 * rel_other
    alignment = _query_alignment_score(paper, query, needs)
    authority = _source_authority_score(paper)
    recency = _recency_score(paper.get("published", ""))
    primary_score = _primary_source_score(paper, answer_spec)
    entity_score = _canonical_entity_score(paper, answer_spec)
    year_score = _origin_year_score(paper, answer_spec)
    survey_penalty = _survey_penalty(paper, answer_spec)
    req_match = _requirement_match_score(paper, requirement_texts, requirement_vecs)
    primary_fit = 0.8 * primary_score + 0.2 * max(entity_score, year_score)

    lexical_signal = max(alignment, req_match)
    collision_penalty = _phrase_collision_penalty(paper, semantic, lexical_signal)

    if is_canonical:
        score = (
            0.34 * req_match
            + 0.26 * primary_fit
            + 0.18 * semantic
            + 0.10 * authority
            + 0.06 * recency
            + 0.06 * alignment
            - survey_penalty
            - collision_penalty
        )
    else:
        score = (
            0.34 * req_match
            + 0.22 * semantic
            + 0.16 * authority
            + 0.14 * recency
            + 0.08 * alignment
            + 0.06 * primary_fit
            - collision_penalty
        )

    if paper.get("_validation_penalty"):
        score *= paper["_validation_penalty"]

    paper["_relevance_orig"] = round(rel_orig, 3)
    paper["_relevance_combined"] = round(semantic, 3)
    paper["_alignment"] = round(alignment, 3)
    paper["_primary_source_score"] = round(primary_score, 3)
    paper["_canonical_entity_score"] = round(entity_score, 3)
    paper["_origin_year_score"] = round(year_score, 3)
    paper["_survey_penalty"] = round(survey_penalty, 3)
    paper["_requirement_match_score"] = round(req_match, 3)
    paper["_collision_penalty"] = round(collision_penalty, 3)
    paper["_source_role"] = _classify_source_role(paper, answer_spec)

    return max(0.0, score)

def _llm_rerank_top_k(top_k: list[dict], state: AgentState, answer_spec: dict) -> list[dict]:
    if not top_k:
        return top_k
    if not getattr(settings, "LLM_RERANK_ENABLED", True):
        return top_k
    if is_llm_rate_limited():
        print("[rank] LLM rerank skipped: rate-limit cooldown")
        return top_k
    if not (answer_spec.get("requirements") or answer_spec.get("canonical_entities")):
        return top_k

    mode = state.get("response_mode", "normal")

    limit = (
        getattr(settings, "RERANK_MAX_CANDIDATES_NORMAL", 6)
        if mode == "normal"
        else getattr(settings, "RERANK_MAX_CANDIDATES_RESEARCH", 10)
    )
    candidates = top_k[: max(1, int(limit))]

    requirements = "\n".join(
        f"- {r.get('text') or ''}"
        for r in (answer_spec.get("requirements") or [])[:10]
    )
    canonical = "\n".join(
        f"- {e.get('name') or ''} (expected primary source: {e.get('expected_primary_source') or 'unknown'})"
        for e in (answer_spec.get("canonical_entities") or [])[:6]
    )
    papers_block = "\n\n".join(
        f"[paper_id={i}]\n"
        f"Title: {p.get('title', '')}\n"
        f"Year: {p.get('published', '')}\n"
        f"Source: {p.get('source', '')}\n"
        f"Citations: {p.get('citation_count', 0)}\n"
        f"Abstract: {(p.get('summary') or p.get('text') or '')[:350]}"
        for i, p in enumerate(candidates)
    )

    prompt = f"""You are a research source evaluator.
USER QUESTION:
{state.get('query', '')}
ANSWER REQUIREMENTS:
{requirements or 'none'}
CANONICAL ENTITIES:
{canonical or 'none'}
PAPERS:
{papers_block}

Score how well each paper is suited to answering the user's exact question.
Do not reward general topical relatedness.
Reward whether each paper can support specific required claims.
If the question asks for an original architecture, derivation, theory, or historical origin, give high primary_source_fit only to original/canonical sources.

For each paper, return one object with:
paper_id
answers_question
primary_source_fit
requirement_coverage
source_role
reason

Use the [paper_id=N] markers above.
Return ONLY a JSON object with a single key "judgments".
"""
    try:
        llm = get_llm(temperature=0, task="fast")
        raw = llm.invoke_json_mode(
            [
                SystemMessage(content="You are a research source evaluator. Return only JSON."),
                HumanMessage(content=prompt),
            ],
            schema=None,
            config={"timeout": 10 if mode == "normal" else 14},
        )
    except Exception as e:
        print(f"[rank] LLM rerank failed, keeping retrieval scores: {type(e).__name__}: {e}")
        return top_k

    judgment_map = _normalize_judgments(raw, len(candidates))
    if not judgment_map:
        print("[rank] LLM rerank produced no usable judgments, keeping retrieval scores")
        return top_k

    for i, p in enumerate(candidates):
        j = judgment_map.get(i)
        if not j:
            continue
        retrieval_score = float(p.get("final_score") or 0.0)
        llm_score = float(j["answers_question"])
        if answer_spec.get("primary_source_required"):
            llm_score = (
                0.7 * float(j["answers_question"])
                + 0.3 * float(j["primary_source_fit"])
            )
        p["final_score"] = round(0.55 * retrieval_score + 0.45 * llm_score, 3)
        p["_llm_answers_question"] = round(float(j["answers_question"]), 3)
        p["_llm_primary_source_fit"] = round(float(j["primary_source_fit"]), 3)
        p["_llm_reason"] = j["reason"]
        p["_llm_requirement_coverage"] = j["requirement_coverage"]
        if j["source_role"] and j["source_role"] != "background":
            p["_source_role"] = j["source_role"]

    candidates.sort(key=lambda p: float(p.get("final_score") or 0.0), reverse=True)
    return candidates + top_k[len(candidates):]

def _phrase_collision_penalty(paper: dict, semantic: float, alignment: float) -> float:
    if alignment <= 0:
        return 0.0
    gap = alignment - semantic
    if gap <= 0.12:
        return 0.0
    return min(0.90, (gap - 0.12) * 2.5)

def _weighted_score(paper: dict, orig_vec: list[float], other_vecs: list[list[float]], query: str, needs: list) -> float:
    vec = paper.get("abstract_vec")
    if vec is None:
        paper["_relevance_orig"] = 0.0
        paper["_relevance_combined"] = 0.0
        return 0.0

    rel_orig = similarity(orig_vec, vec)
    rel_other = max((similarity(v, vec) for v in other_vecs), default=0.0)
    semantic = 0.65 * rel_orig + 0.35 * rel_other
    alignment = _query_alignment_score(paper, query, needs)
    authority = _source_authority_score(paper)
    recency = _recency_score(paper.get("published", ""))
    type_bonus = _paper_type_bonus(paper, needs)
    collision_penalty = _phrase_collision_penalty(paper, semantic, alignment)

    score = (
        0.46 * semantic
        + 0.28 * alignment
        + 0.17 * authority
        + 0.09 * recency
        + type_bonus
        - collision_penalty
    )
    if paper.get("_validation_penalty"):
        score *= paper["_validation_penalty"]

    paper["_relevance_orig"] = round(rel_orig, 3)
    paper["_relevance_combined"] = round(semantic, 3)
    paper["_alignment"] = round(alignment, 3)
    paper["_collision_penalty"] = round(collision_penalty, 3)
    return max(0.0, score)

def _ensure_vectors(papers: list[dict]) -> None:
    missing = [p for p in papers if p.get("abstract_vec") is None]
    if not missing:
        return
    vecs = embed_texts([(p.get("summary") or p.get("title") or "")[:1000] for p in missing])
    for p, vec in zip(missing, vecs):
        p["abstract_vec"] = vec

def _marginal_gain_select(prefiltered: list[dict], needs: list, target_k: int) -> list[dict]:
    selected: list[dict] = []
    remaining = list(prefiltered)
    covered_need_ids: set[str] = set()

    while remaining and len(selected) < target_k:
        best = None
        best_score = -1e9
        for p in remaining:
            novelty = 0.0
            p_text = " ".join([p.get("title", ""), p.get("summary", "")[:1200]])
            for n in needs:
                ov = need_overlap_score(n.text, p_text)
                if ov >= 0.30 and n.need_id not in covered_need_ids:
                    novelty += 0.18 * n.priority

            redundancy_penalty = 0.0
            if selected and p.get("abstract_vec") is not None:
                similarities = [
                    similarity(p["abstract_vec"], s["abstract_vec"])
                    for s in selected
                    if s.get("abstract_vec") is not None
                ]
                if similarities:
                    redundancy_penalty = 0.12 * max(similarities)

            candidate_score = p.get("final_score", 0.0) + novelty - redundancy_penalty
            if candidate_score > best_score:
                best_score = candidate_score
                best = p

        if best is None:
            break
        selected.append(best)
        remaining.remove(best)

        b_text = " ".join([best.get("title", ""), best.get("summary", "")[:1200]])
        for n in needs:
            if n.need_id in covered_need_ids:
                continue
            if need_overlap_score(n.text, b_text) >= 0.30:
                covered_need_ids.add(n.need_id)
    return selected

def _source_tier(paper: dict) -> int:
    source = (paper.get("source") or "").lower()
    cites = paper.get("citation_count", 0) or 0
    title = (paper.get("title") or "").lower()
    link = (paper.get("link") or "").lower()

    if paper.get("_primary_candidate") or paper.get("_foundational_candidate"):
        return 1
    if source == "web":
        authoritative = (
            ".gov", "who.int", "iea.org", "irena.org", "imf.org",
            "worldbank.org", "un.org", "ipcc.ch", "nih.gov", "cdc.gov",
            "nist.gov", "iso.org", "oecd.org", "federalreserve.gov",
        )
        return 1 if any(d in link for d in authoritative) else 4

    is_synthesis = any(k in title for k in (
        "systematic review", "meta-analysis", "assessment report",
        "review", "overview",
    ))
    if is_synthesis and cites >= 200:
        return 2
    if cites >= 1000:
        return 2
    if source in ("openalex", "arxiv", "semantic_scholar", "semanticscholar"):
        return 3
    return 4


def _foundational_selection_score(paper: dict, min_year: int | None) -> float:
    """
    Rank foundational candidates by ORIGIN-likelihood, not fame.

    Raw citation count can be dominated by surveys or famous-but-not-
    origin papers, so combine independent signals:
      1. explicit title match  – hardcoded known origin (guaranteed)
      2. convergence hits      – cited by several independent anchors
      3. influential ratio     – later work BUILDS ON it (Semantic Scholar)
      4. earliness             – origins predate the candidate set
      5. survey penalty        – surveys are cited, not built upon
    """
    score = 0.5 * float(paper.get("final_score") or 0.0)

    if paper.get("_foundational_source") == "explicit":
        score += 1.0

    hits = min(int(paper.get("_convergence_hits") or 0), 3)
    score += 0.30 * hits

    cites = paper.get("citation_count", 0) or 0
    infl = paper.get("influential_citation_count", 0) or 0
    if cites >= 50 and infl > 0:
        score += 0.35 * min(1.0, (infl / cites) * 3.0)

    year = _paper_year(paper)
    if year and min_year and year <= min_year + 3:
        score += 0.20

    title = (paper.get("title") or "").lower()
    if any(w in title for w in ("survey", "review", "overview", "comprehensive")):
        score -= 0.50

    return score


def _paper_year(paper: dict) -> int | None:
    """Centralized year extraction from any paper metadata format."""
    for key in ("published", "publication_year", "year"):
        value = paper.get(key)
        if value is None:
            continue
        match = _re.search(r"\b(19|20)\d{2}\b", str(value))
        if match:
            return int(match.group(0))
    return None

def _study_type_matches(paper: dict, required_type: str) -> bool:
    """
    Normalized study-type detection using regex patterns.
    Handles abbreviations, alternate spellings, and descriptive phrasing.
    """
    blob = " ".join([
        str(paper.get("title") or ""),
        str(paper.get("summary") or ""),
        str(paper.get("study_type") or ""),
        str(paper.get("type") or ""),
        str(paper.get("venue") or ""),
    ]).lower()

    rt = required_type.lower().strip()

    if rt in ("rct", "randomized controlled trial", "randomised controlled trial"):
        patterns = [
            r"\brandomized\b",
            r"\brandomised\b",
            r"\brandomized\s+controlled\b",
            r"\brandomised\s+controlled\b",
            r"\brct\b",
            r"\brcts\b",
            r"\bplacebo[- ]?controlled\b",
            r"\bdouble[- ]?blind\b",
        ]
        return any(_re.search(p, blob) for p in patterns)

    if rt in ("meta-analysis", "meta analysis", "systematic review"):
        return (
            "meta-analysis" in blob
            or "meta analysis" in blob
            or "metaanalysis" in blob
            or "systematic review" in blob
            or "systematic-review" in blob
        )

    if rt in ("cohort", "cohort study"):
        return "cohort" in blob

    if rt in ("case-control", "case control"):
        return "case-control" in blob or "case control" in blob

    if rt in ("guideline", "consensus statement"):
        return "guideline" in blob or "consensus statement" in blob

    return rt in blob

def _check_paper_eligibility(
    paper: dict,
    evidence_contract: dict,
) -> tuple[str, str]:
    """
    Check if a paper satisfies the hard constraints of the evidence contract.
    Returns (eligibility_status, reason).
    """
    if not evidence_contract:
        return "eligible", ""

    constraints = evidence_contract.get("constraints", [])
    hard_constraints = [c for c in constraints if c.get("strength") == "hard"]

    if not hard_constraints:
        return "eligible", ""

    for constraint in hard_constraints:
        field = constraint.get("field", "")
        operator = constraint.get("operator", "")
        value = constraint.get("value")

        if field == "publication_year":
            year = _paper_year(paper)
            if year is None:
                continue
            try:
                required_year = int(value)
            except (ValueError, TypeError):
                continue
            if operator == "gte" and year < required_year:
                return "ineligible", f"Year {year} < required {required_year}"
            if operator == "lte" and year > required_year:
                return "ineligible", f"Year {year} > required {required_year}"

        elif field == "study_type":
            required_type = str(value)
            if not _study_type_matches(paper, required_type):
                return (
                    "ineligible",
                    f"Study type '{required_type}' not detected",
                )

    return "eligible", ""

def _evidence_contract_score(paper: dict, evidence_contract: dict) -> float:
    """Score how well a paper satisfies preferred constraints (0-1)."""
    if not evidence_contract:
        return 0.5

    constraints = evidence_contract.get("constraints", [])
    preferred = [c for c in constraints if c.get("strength") == "preferred"]
    if not preferred:
        return 0.5

    score = 0.0
    for constraint in preferred:
        field = constraint.get("field", "")
        value = str(constraint.get("value", "")).lower()
        title = (paper.get("title") or "").lower()
        summary = (paper.get("summary") or "").lower()
        blob = title + " " + summary

        if field in (
            "comparator", "intervention", "outcome",
            "population", "study_type",
        ):
            if value in blob:
                score += 1.0
        elif field == "geography":
            if value in blob:
                score += 1.0

    return score / len(preferred) if preferred else 0.5


def rank_node(state: AgentState) -> AgentState:
    papers = state.get("raw_search_results", [])
    is_uploaded_only = state.get("evidence_mode") == "uploaded"

    if not papers:
        return {
            "ranked_papers": [],
            "needs_retry": False if is_uploaded_only else True,
            "papers_below_threshold": 0,
            "low_confidence_results": False,
            "coverage_gaps": ["No sources retrieved"],
            "term_coverage": {},
            "eligible_papers": [],
            "background_papers": [],
            "ineligible_papers": [],
        }

    if is_uploaded_only:
        print(
            f"[rank] uploaded mode: skipping merge_duplicate_papers "
            f"for {len(papers)} passage(s)"
        )
    else:
        papers = merge_duplicate_papers(papers)
    _ensure_vectors(papers)

    original_query = state.get("query", "")
    search_queries = state.get("search_queries", [original_query])
    needs = derive_research_needs(
        original_query,
        state.get("query_understanding") or {},
        state.get("report_plan") or {},
    )
    orig_vec = state.get("query_embedding") or embed_texts([original_query])[0]
    other_queries = [q for q in search_queries if q != original_query]
    other_vecs = embed_texts(other_queries) if other_queries else []

    answer_spec = state.get("answer_spec") or {}
    requirement_texts: list[str] = []
    requirement_vecs: list[list[float]] = []
    if answer_spec:
        for r in (answer_spec.get("requirements") or []):
            text = str(r.get("text") or "").strip()
            if text and text not in requirement_texts:
                requirement_texts.append(text)
        requirement_texts = requirement_texts[:8]
        if requirement_texts:
            requirement_vecs = embed_texts(requirement_texts)

    question_types = answer_spec.get("question_types", [])
    is_canonical = bool(
        answer_spec.get("primary_source_required")
        or "mathematical_derivation" in question_types
        or "technical_explanation" in question_types
    )

    all_papers = []
    for p in papers:
        if answer_spec and requirement_vecs:
            p["final_score"] = round(
                _answer_spec_weighted_score(
                    p, orig_vec, other_vecs, original_query, needs,
                    answer_spec, requirement_texts, requirement_vecs, is_canonical,
                ),
                3,
            )
        else:
            p["final_score"] = round(_weighted_score(p, orig_vec, other_vecs, original_query, needs), 3)
        all_papers.append(p)

    all_papers.sort(key=lambda p: p.get("final_score", 0.0), reverse=True)

    ABSOLUTE_MIN_SCORE_FLOOR = 0.22
    HARD_SEMANTIC_FLOOR = 0.30

    if is_uploaded_only:
        prefiltered = all_papers[:PRE_FILTER_N]
    else:
        prefiltered = [
            p for p in all_papers[:PRE_FILTER_N]
            if p.get("final_score", 0.0) >= max(settings.MIN_FINAL_SCORE * 0.65, ABSOLUTE_MIN_SCORE_FLOOR)
            and p.get("_relevance_combined", 0.0) >= HARD_SEMANTIC_FLOOR
        ]

    low_confidence_results = False
    if len(prefiltered) < settings.TOP_K_PAPERS_MIN and not is_uploaded_only:
        low_confidence_results = True
        top_ids = [p.get("openalex_id") for p in all_papers[:3] if p.get("openalex_id")]
        if top_ids:
            extra = fetch_openalex_citation_graph(top_ids, limit_per_paper=3)
            extra = merge_duplicate_papers(extra)
            _ensure_vectors(extra)
            for p in extra:
                p["_from_citation_graph"] = True
                if answer_spec and requirement_vecs:
                    p["final_score"] = round(
                        _answer_spec_weighted_score(
                            p, orig_vec, other_vecs, original_query, needs,
                            answer_spec, requirement_texts, requirement_vecs, is_canonical,
                        ),
                        3,
                    )
                else:
                    p["final_score"] = round(_weighted_score(p, orig_vec, other_vecs, original_query, needs), 3)
            all_papers = merge_duplicate_papers(all_papers + extra)
            all_papers.sort(key=lambda p: p.get("final_score", 0.0), reverse=True)
            prefiltered = [
                p for p in all_papers[:PRE_FILTER_N]
                if p.get("final_score", 0.0) >= max(settings.MIN_FINAL_SCORE * 0.65, ABSOLUTE_MIN_SCORE_FLOOR)
            ]

    if is_uploaded_only:
        target_k_setting = len(prefiltered)
        print(
            f"[rank] uploaded mode: target_k_setting={target_k_setting} "
            f"(actual retrieved chunk count, overriding target_paper_k="
            f"{state.get('target_paper_k')!r})"
        )
    else:
        target_k_setting = int(state.get("target_paper_k") or settings.TOP_K_PAPERS_MAX)
        target_k_setting = max(settings.TOP_K_PAPERS_MIN, target_k_setting)
        target_k_setting = min(settings.TOP_K_PAPERS_MAX, target_k_setting)
    target_k = min(len(prefiltered), target_k_setting)

    top_k = _marginal_gain_select(prefiltered, needs, target_k) if prefiltered else []

    if answer_spec:
        primary_candidates = [
            p for p in all_papers
            if p.get("_primary_candidate")
            or (p.get("_primary_source_score") or 0) >= 0.8
        ]
        for p in primary_candidates[:3]:
            if p not in top_k:
                top_k.append(p)
        if len(top_k) > 1:
            top_k = sorted(top_k, key=lambda p: p.get("final_score", 0.0), reverse=True)

    foundational_in_topk = [
        p for p in top_k if p.get("_foundational_candidate")
    ]
    if not foundational_in_topk:
        foundational_candidates = [
            p for p in all_papers if p.get("_foundational_candidate")
        ]
        if foundational_candidates:
            candidate_years = [
                y
                for y in (_paper_year(p) for p in foundational_candidates)
                if y
            ]
            min_year = min(candidate_years) if candidate_years else None
            best_foundational = max(
                foundational_candidates,
                key=lambda p: _foundational_selection_score(p, min_year),
            )
            top_k.append(best_foundational)
            top_k.sort(key=lambda p: p.get("final_score", 0), reverse=True)

    if answer_spec and not is_uploaded_only:
        top_k = _llm_rerank_top_k(top_k, state, answer_spec)

    for p in top_k:
        p["_source_tier"] = _source_tier(p)

    for p in top_k:
        p["_is_origin_paper"] = bool(
            p.get("_primary_candidate")
            or (
                p.get("_source_role") == "primary"
                and (p.get("_primary_source_score") or 0) >= 0.8
            )
        )

    coverage = assess_coverage(needs, top_k)
    coverage_gaps = [
        c.get("need", "")
        for c in coverage.values()
        if c.get("status") == "unsupported"
    ]

    avg_semantic = sum(p.get("_relevance_combined", 0.0) for p in prefiltered[:settings.TOP_K_PAPERS_MIN]) / max(1, min(len(prefiltered), settings.TOP_K_PAPERS_MIN))
    if avg_semantic < 0.38:
        low_confidence_results = True
        if "Retrieved sources lack direct domain relevance." not in coverage_gaps:
            coverage_gaps.append("Retrieved sources lack direct domain relevance.")

    primary_source_present = False
    if answer_spec.get("primary_source_required"):
        primary_source_present = any(
            p.get("_primary_candidate")
            or (p.get("_primary_source_score") or 0) > 0.8
            for p in top_k
        )
        if not primary_source_present:
            coverage_gaps.append("Primary source could not be confidently retrieved. Confidence reduced.")

    needs_retry = (
        not is_uploaded_only
        and (
            len(top_k) < settings.TOP_K_PAPERS_MIN
            or len(coverage_gaps) > max(2, len(coverage) // 3)
        )
        and state.get("search_attempts", 0) < state.get("max_search_attempts", 2)
    )

    evidence_contract = state.get("evidence_contract") or {}
    eligible_papers = []
    ineligible_papers = []
    background_papers = []

    for p in top_k:
        eligibility, reason = _check_paper_eligibility(p, evidence_contract)
        p["_eligibility"] = eligibility
        p["_eligibility_reason"] = reason
        if eligibility == "eligible":
            eligible_papers.append(p)
        else:
            ineligible_papers.append(p)

    if len(eligible_papers) < 3 and ineligible_papers:
        for p in ineligible_papers[:3]:
            p["_source_role"] = "background"
            background_papers.append(p)

    eligible_papers.sort(
        key=lambda p: p.get("final_score", 0),
        reverse=True,
    )

    for p in eligible_papers:
        contract_score = _evidence_contract_score(p, evidence_contract)
        p["final_score"] = round(
            p.get("final_score", 0) * 0.8 + contract_score * 0.2,
            3,
        )

    eligible_papers.sort(
        key=lambda p: p.get("final_score", 0),
        reverse=True,
    )

    return {
        "ranked_papers": top_k,
        "needs_retry": state.get("needs_retry", False) or needs_retry,
        "papers_below_threshold": max(0, len(all_papers) - len(prefiltered)),
        "low_confidence_results": low_confidence_results,
        "coverage_gaps": coverage_gaps,
        "term_coverage": coverage,
        "primary_source_present": primary_source_present,
        "eligible_papers": eligible_papers,
        "background_papers": background_papers,
        "ineligible_papers": ineligible_papers,
    }