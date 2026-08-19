import json
import re

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Literal, List
from app.agents.nodes.summarize_node import _normalize_latex_delimiters
from concurrent.futures import ThreadPoolExecutor
from app.agents.schemas import AnswerClaim, CitationAudit, MathVerification
from app.agents.state import AgentState
from app.services.llm_client import get_llm
from app.services.reference_builder import extract_paper_ids


_CLAIM_PROMPT = """Extract the checkable factual claims from this draft answer.

USER QUESTION:
{query}

DRAFT ANSWER:
{draft}

Rules:
Extract only claims that make a factual assertion (origin, definition, mechanism, equation, comparison, empirical result, limitation, application).
For each claim, list the [paper_id=N] citation markers found in or immediately after the sentence.
Never invent citation ids: only use ids that appear in the draft as [paper_id=N].
Set requires_primary_source=true for claims about the origin/history of a method, an equation/formula, or a named architecture that the question asks about.
Use the field name "text" for the claim sentence.
Return at most 25 claims.
Return ONLY a JSON object with a single key "claims".
"""

_AUDIT_PROMPT = """Judge whether each claim is properly supported by its cited papers.

CLAIMS:
{claims_json}

AVAILABLE PAPERS:
{papers_block}

For each claim return one CitationAudit object with the same claim_id.
For every claim decide:
citation_valid: whether the cited papers exist and plausibly support the claim.
support_level: "direct" (paper states it explicitly), "derived" (paper states the premise), "supported" (related evidence), "background" (contextual only), "unsupported" (no evidence).
source_role: "primary" (original/canonical source), "secondary", "survey", "application", "background", "none".
is_quantitative: true if the claim asserts a specific number, percentage, cost, date, capacity, or measurable quantity.
epistemic_status: exactly one of:
- "verified": a cited source directly supports the claim.
- "uncertain": partially supported, dependent on assumptions, or sources disagree.
- "unknown": the draft correctly acknowledges that the data/evidence is unavailable. Proper abstention is GOOD — mark it "unknown", NOT "unsupported".
- "unsupported": asserted as fact with no support from any cited source.
If the claim contains a specific number and the cited paper does NOT contain or directly support that figure, set support_level to "unsupported".
If the claim would be better supported by a different paper, set corrected_citation_paper_id to that paper's id.

Return ONLY a JSON object with a single key "audits" containing a list of CitationAudit objects.
"""

_MATH_PROMPT = """Verify every equation and mathematical statement in the draft answer below.

USER QUESTION:
{query}

EXPECTED CANONICAL EQUATIONS (verify these if present):
{expected_equations}

DRAFT EQUATIONS:
{draft_excerpt}

For each equation found, produce one EquationCheck:
- original_text: the equation as written in the draft.
- canonical_form: the standard form if the draft deviates.
- is_correct: true only if the equation is correct.
- issues: what is wrong, if anything.
- corrected_form: the fixed equation if wrong.
- explanation: one short sentence.

Set critical_math_failed=true if any expected canonical equation is missing or written incorrectly.

Return ONLY a JSON object matching MathVerification.
"""

_QUANTITATIVE_CLAIM_RE = re.compile(
    r"\d[\d,\.]*\s*(?:%|percent|billion|million|trillion|thousand|"
    r"USD|EUR|GBP|GW|MW|kW|TW|TWh|MWh|kWh|GWh|"
    r"Gt|Mt|kt|tonnes?|tons?|°C|degrees?|dB|"
    r"km|miles?|meters?|hectares?|"
    r"per (?:year|capita|hour|unit)|/year|annually)",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"^(19\d{2}|20\d{2})$")
_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")

_ABSTENTION_MARKERS = (
    "unknown", "no data", "no source provides", "no source states",
    "not available", "unavailable", "insufficient evidence",
    "cannot be determined", "cannot be quantified", "cannot responsibly",
    "no reliable", "not possible to quantify", "data gap", "evidence gap",
    "evidence is limited", "evidence is lacking", "remains uncertain",
    "is not known", "are not known", "was not found",
)

_HEDGE_MARKERS = (
    "approximately", "roughly", "around", "estimated", "estimate:",
    "inference:", "speculative:", "could", "may range", "depending on",
    "plausibly", "order of magnitude", "likely between", "~",
)


class _ExtractedClaim(BaseModel):
    """
    Local schema for LLM claim extraction.

    This intentionally does NOT require the LLM to provide an ID.
    IDs are assigned deterministically in Python.
    """

    text: str = ""

    claim_type: Literal[
        "historical_origin",
        "definition",
        "equation",
        "mechanism",
        "comparison",
        "empirical_result",
        "limitation",
        "application",
        "inference",
    ] = "definition"

    cited_paper_ids: List[int] = Field(default_factory=list)
    requires_primary_source: bool = False

    @model_validator(mode="before")
    @classmethod
    def _normalize_claim_aliases(cls, data):
        """
        Accept common aliases for the claim sentence.
        """
        if isinstance(data, dict):
            data = dict(data)

            if not data.get("text"):
                for key in (
                    "claim",
                    "sentence",
                    "statement",
                    "assertion",
                    "claim_text",
                ):
                    value = data.get(key)
                    if value:
                        data["text"] = str(value)
                        break

            if data.get("cited_paper_ids") is None:
                data["cited_paper_ids"] = []

        return data

    @field_validator("cited_paper_ids", mode="before")
    @classmethod
    def _normalize_cited_paper_ids(cls, value):
        if value is None:
            return []

        if isinstance(value, list):
            out = []
            for item in value:
                try:
                    out.append(int(item))
                except Exception:
                    pass
            return out

        try:
            return [int(value)]
        except Exception:
            return []


class _ExtractedClaimBatch(BaseModel):
    claims: List[_ExtractedClaim] = Field(default_factory=list)


class _ClaimBatch(BaseModel):
    claims: list[AnswerClaim] = Field(default_factory=list)


class _AuditBatch(BaseModel):
    audits: list[CitationAudit] = Field(default_factory=list)


def _draft_truncated(draft: str, limit: int = 6000) -> str:
    return (draft or "")[:limit]


def _papers_block(
    papers: list[dict],
    claims: list[dict],
    limit: int = 12,
) -> str:
    """
    Build a compact paper block for citation audit.

    Only papers actually cited by the claims are included.
    If no cited ids exist, use a small fallback set.
    """
    cited_indices: set[int] = set()

    for claim in claims:
        for pid in claim.get("cited_paper_ids", []):
            try:
                idx = int(pid)
            except Exception:
                continue

            if 0 <= idx < len(papers):
                cited_indices.add(idx)

    if cited_indices:
        selected_indices = sorted(cited_indices)[:limit]
    else:
        selected_indices = list(range(min(5, len(papers))))

    blocks = []

    for idx in selected_indices:
        paper = papers[idx]

        title = paper.get("title", "")
        year = paper.get("published", "")
        source = paper.get("source", "")
        role = paper.get("_source_role") or "secondary"

        blocks.append(
            f"[paper_id={idx}]\n"
            f"Title: {title}\n"
            f"Year: {year}\n"
            f"Source: {source}\n"
            f"Role: {role}"
        )

    return "\n\n".join(blocks)


def _math_excerpt(draft: str, limit: int = 3000) -> str:
    """
    Extract only LaTeX math blocks for efficient math verification.

    Deduplicates repeated equations before returning them. Without this,
    a draft that states the same formula multiple times (a known upstream
    repetition issue) causes the math-verification LLM call to redundantly
    re-verify identical equations, burning output tokens until the
    response truncates mid-JSON and the whole verification step fails.
    """
    draft = _normalize_latex_delimiters(draft or "")
    draft = draft or ""

    blocks = re.findall(
        r"(\$\$.*?\$\$|\$[^$\n]+?\$)",
        draft,
        re.DOTALL,
    )

    if not blocks:
        return ""

    seen = set()
    deduped = []

    for b in blocks:
        key = re.sub(r"\s+", " ", b).strip()

        if key in seen:
            continue

        seen.add(key)
        deduped.append(b)

    return "\n".join(deduped)[:limit]


def _extract_claims_llm(state: AgentState, draft: str) -> list[dict] | None:
    query = state.get("query", "")
    mode = state.get("response_mode", "normal")
    timeout = 8 if mode == "normal" else 12

    try:
        llm = get_llm(temperature=0, task="structured")

        result = llm.invoke_json_mode(
            [
                SystemMessage(
                    content=(
                        "You are a rigorous fact-checker. "
                        "Return only the requested JSON."
                    )
                ),
                HumanMessage(
                    content=_CLAIM_PROMPT.format(
                        query=query,
                        draft=_draft_truncated(draft),
                    )
                ),
            ],
            schema=_ExtractedClaimBatch,
            config={"timeout": timeout},
        )

        if isinstance(result, dict):
            raw_claims = result.get("claims") or []
        else:
            raw_claims = result.claims or []

    except Exception as e:
        print(f"[verify] claim extraction failed: {type(e).__name__}: {e}")
        return None

    out = []

    for i, raw_claim in enumerate(raw_claims):
        if isinstance(raw_claim, dict):
            try:
                raw_claim = _ExtractedClaim.model_validate(raw_claim)
            except Exception:
                continue

        claim_text = str(raw_claim.text or "").strip()
        if not claim_text:
            continue

        claim_dict = raw_claim.model_dump()
        claim_dict["id"] = f"claim_{i + 1}"
        claim_dict["text"] = claim_text

        try:
            final_claim = AnswerClaim.model_validate(claim_dict)
            out.append(final_claim.model_dump())
        except Exception:
            continue

    return out


def _extract_claims_deterministic(
    draft: str,
    max_claims: int = 15,
) -> list[dict]:
    claims = []

    for line in (draft or "").splitlines():
        ids = [int(x) for x in extract_paper_ids(line)]

        if not ids:
            continue

        text = re.sub(r"\[paper_id=\d+\]", "", line).strip()

        if len(text) < 20:
            continue

        claims.append(
            {
                "id": f"c{len(claims) + 1}",
                "text": text[:300],
                "claim_type": "inference",
                "cited_paper_ids": ids,
                "requires_primary_source": False,
            }
        )

        if len(claims) >= max_claims:
            break

    return claims


def _audit_claims_llm(
    state: AgentState,
    claims: list[dict],
    papers: list[dict],
) -> list[dict] | None:
    mode = state.get("response_mode", "normal")
    timeout = 10 if mode == "normal" else 14

    claims_json = json.dumps(claims[:25], default=str)

    try:
        llm = get_llm(temperature=0, task="structured")

        result = llm.invoke_json_mode(
            [
                SystemMessage(
                    content=(
                        "You are a citation auditor. "
                        "Return only the requested JSON."
                    )
                ),
                HumanMessage(
                    content=_AUDIT_PROMPT.format(
                        claims_json=claims_json,
                        papers_block=_papers_block(papers, claims),
                    )
                ),
            ],
            schema=_AuditBatch,
            config={"timeout": timeout},
        )

        if isinstance(result, dict):
            audits = result.get("audits") or []
        else:
            audits = result.audits or []

    except Exception as e:
        print(f"[verify] citation audit failed: {type(e).__name__}: {e}")
        return None

    out = []

    for audit in audits:
        if isinstance(audit, dict):
            try:
                audit = CitationAudit.model_validate(audit)
            except Exception:
                continue

        out.append(audit.model_dump())

    return out


def _audit_claims_deterministic(
    claims: list[dict],
    papers: list[dict],
) -> list[dict]:
    audits = []

    for c in claims:
        ids = [
            i
            for i in c.get("cited_paper_ids", [])
            if isinstance(i, int) and 0 <= i < len(papers)
        ]

        if not ids:
            audits.append(
                {
                    "claim_id": c.get("id", ""),
                    "claim_text": c.get("text", ""),
                    "citation_valid": False,
                    "support_level": "unsupported",
                    "source_role": "none",
                    "reason": "No valid [paper_id=N] citation found for this claim.",
                    "corrected_citation_paper_id": None,
                    "is_quantitative": bool(
                        _QUANTITATIVE_CLAIM_RE.search(c.get("text", ""))
                    ),
                    "epistemic_status": "unsupported",
                }
            )
            continue

        roles = {
            papers[i].get("_source_role") or "secondary"
            for i in ids
        }

        has_primary = any(
            papers[i].get("_primary_candidate")
            for i in ids
        )

        has_direct = any(
            float(
                papers[i].get("_relevance_orig")
                or papers[i].get("final_score")
                or 0.0
            ) >= 0.5
            for i in ids
        )

        if has_primary:
            support = "direct"
            role = "primary"
        elif has_direct:
            support = "supported"
            role = "secondary"
        else:
            support = "background"
            role = "secondary"

        is_quant = bool(
            _QUANTITATIVE_CLAIM_RE.search(c.get("text", ""))
        )

        if support == "direct":
            epi = "verified"
        elif support in ("supported", "background"):
            epi = "uncertain" if is_quant else "verified"
        else:
            epi = "unsupported"

        audits.append(
            {
                "claim_id": c.get("id", ""),
                "claim_text": c.get("text", ""),
                "citation_valid": True,
                "support_level": support,
                "source_role": role,
                "reason": (
                    "Deterministic fallback audit: papers "
                    + ", ".join(str(i) for i in ids)
                    + " (roles: "
                    + ", ".join(sorted(roles))
                    + ")."
                ),
                "corrected_citation_paper_id": None,
                "is_quantitative": is_quant,
                "epistemic_status": epi,
            }
        )

    return audits


def _math_verify_llm(
    state: AgentState,
    draft: str,
    answer_spec: dict,
) -> dict | None:
    query = state.get("query", "")
    mode = state.get("response_mode", "normal")
    timeout = 10 if mode == "normal" else 14

    expected = (answer_spec.get("expected_equations") or [])[:10]
    excerpt = _math_excerpt(draft)

    if not excerpt and not expected:
        return _math_verify_deterministic(answer_spec)

    try:
        llm = get_llm(temperature=0, task="fast")

        result = llm.invoke_json_mode(
            [
                SystemMessage(
                    content=(
                        "You are a math verifier. "
                        "Return only the requested JSON."
                    )
                ),
                HumanMessage(
                    content=_MATH_PROMPT.format(
                        query=query,
                        expected_equations=(
                            "\n".join(expected)
                            if expected
                            else "none"
                        ),
                        draft_excerpt=excerpt or "none",
                    )
                ),
            ],
            schema=MathVerification,
            config={"timeout": timeout},
        )

        if isinstance(result, dict):
            mv = MathVerification.model_validate(result)
        else:
            mv = result

    except Exception as e:
        print(f"[verify] math verification failed: {type(e).__name__}: {e}")
        return None

    return mv.model_dump()


def _math_verify_deterministic(answer_spec: dict) -> dict:
    return {
        "checked_equations": [],
        "critical_math_failed": False,
        "notes": "VERIFICATION_SKIPPED: Equation verification skipped (no math blocks or LLM unavailable).",
    }


def _primary_source_present(
    claims: list[dict],
    audits: list[dict],
    papers: list[dict],
    answer_spec: dict,
) -> bool:
    primary_papers = {
        i
        for i, p in enumerate(papers)
        if p.get("_primary_candidate")
        or p.get("_source_role") == "primary"
    }

    if not primary_papers:
        return False

    if not answer_spec.get("primary_source_required"):
        return True

    required_claims = [
        c
        for c in claims
        if c.get("requires_primary_source")
    ]

    if not required_claims:
        return True

    audit_by_claim = {
        a.get("claim_id"): a
        for a in audits
    }

    for claim in required_claims:
        cited = [
            i
            for i in claim.get("cited_paper_ids", [])
            if isinstance(i, int)
        ]

        if any(i in primary_papers for i in cited):
            continue

        audit = audit_by_claim.get(claim.get("id")) or {}

        if audit.get("source_role") == "primary":
            continue

        corrected = audit.get("corrected_citation_paper_id")

        if isinstance(corrected, int) and corrected in primary_papers:
            continue

        return False

    return True


def _min_confidence(current: str, cap: str) -> str:
    order = {
        "low": 0,
        "medium": 1,
        "high": 2,
    }

    if order.get(current, 1) > order.get(cap, 1):
        return cap

    return current

def _detect_abstentions(draft: str) -> int:
    """Count honest abstention markers in the draft."""
    d = (draft or "").lower()
    count = sum(d.count(m) for m in _ABSTENTION_MARKERS)
    count += d.count("inference:") + d.count("estimate:") + d.count("speculative:")
    return count


def _numbers_in_text(text: str) -> set[str]:
    return {n.replace(",", "") for n in _NUM_RE.findall(text or "")}


def _claim_numbers_fabricated(
    claim_text: str,
    papers: list[dict],
    ledger: dict | None,
) -> int:
    """
    Count numbers in a quantitative claim that appear NOWHERE in the
    evidence set (ledger values + paper titles/abstracts + publication
    years). A number the writer produced that no source contains is the
    signature of invented precision.
    """
    text = re.sub(r"\[paper_id=\d+\]", "", claim_text or "")
    claim_nums = _numbers_in_text(text)
    if not claim_nums:
        return 0

    evidence_nums: set[str] = set()
    for v in (ledger or {}).get("extracted_variables") or []:
        if isinstance(v, dict):
            evidence_nums |= _numbers_in_text(str(v.get("value", "")))
    years: set[str] = set()
    for p in papers:
        blob = (
            f"{p.get('title', '')} "
            f"{(p.get('summary') or p.get('text') or '')[:2000]}"
        )
        evidence_nums |= _numbers_in_text(blob)
        y = str(p.get("published") or "")[:4]
        if y.isdigit():
            years.add(y)

    fabricated = 0
    for num in claim_nums:
        if num in evidence_nums or num in years:
            continue
        if _YEAR_RE.match(num):
            continue 
        fabricated += 1
    return fabricated


def _build_epistemic_report(
    claims: list[dict],
    audits: list[dict],
    draft: str,
    papers: list[dict],
    ledger: dict | None,
    coverage_gaps: list[str],
) -> dict:
    """
    Claim-level uncertainty ledger (manifesto principles 13, 14, 21).
    Separates verified / uncertain / unknown / unsupported, isolates
    unsupported QUANTITATIVE claims, detects fabricated numbers, and
    credits honest abstention.
    """
    audit_by_claim = {a.get("claim_id"): a for a in audits}
    rows: list[dict] = []
    quant_total = 0
    unsupported_quant = 0
    fabricated_total = 0
    uncertain: list[str] = []
    unknown: list[str] = []

    for claim in claims:
        audit = audit_by_claim.get(claim.get("id")) or {}
        text = str(claim.get("text", "") or "")
        is_quant = bool(audit.get("is_quantitative")) or bool(
            _QUANTITATIVE_CLAIM_RE.search(text)
        )
        status = str(audit.get("epistemic_status") or "").strip()
        if status not in ("verified", "uncertain", "unknown", "unsupported"):
            status = "verified" if audit.get("citation_valid") else "unsupported"
        if status == "unsupported" and any(
            h in text.lower() for h in _HEDGE_MARKERS
        ):
            status = "uncertain"

        if is_quant:
            quant_total += 1
            fabricated_total += _claim_numbers_fabricated(text, papers, ledger)
            if status == "unsupported":
                unsupported_quant += 1
        if status == "uncertain":
            uncertain.append(text[:160])
        elif status == "unknown":
            unknown.append(text[:160])

        rows.append(
            {
                "claim": text[:160],
                "quantitative": is_quant,
                "status": status,
            }
        )

    abstentions = _detect_abstentions(draft)
    abstention_rewarded = bool(
        abstentions > 0
        and (
            bool(coverage_gaps)
            or bool((ledger or {}).get("unsupported_variables"))
            or bool(unknown)
        )
    )

    return {
        "quantitative_claims_total": quant_total,
        "unsupported_quantitative_claims": unsupported_quant,
        "fabricated_numbers": fabricated_total,
        "proper_abstentions": abstentions,
        "abstention_rewarded": abstention_rewarded,
        "uncertain_claims": uncertain[:8],
        "unknown_claims": unknown[:8],
        "claim_status_table": rows[:25],
    }


def _apply_confidence_caps(
    dynamic_confidence: dict,
    avg_rel: float,
    state: AgentState,
    epistemic_report: dict | None = None,
) -> dict:
    dc = dict(dynamic_confidence or {})

    answer_confidence = dc.get("answer_confidence") or "medium"
    evidence_quality = dc.get("evidence_quality") or "medium"
    answer_spec = state.get("answer_spec") or {}

    if avg_rel < 0.30:
        answer_confidence = _min_confidence(answer_confidence, "low")
        evidence_quality = _min_confidence(evidence_quality, "low")
    elif avg_rel < 0.50:
        answer_confidence = _min_confidence(answer_confidence, "medium")
        evidence_quality = _min_confidence(evidence_quality, "medium")

    if (
        not state.get("primary_source_present")
        and answer_spec.get("primary_source_required")
    ):
        answer_confidence = _min_confidence(answer_confidence, "medium")
        evidence_quality = _min_confidence(evidence_quality, "medium")

    math_verification = state.get("math_verification") or {}

    if math_verification.get("critical_math_failed"):
        answer_confidence = "low"
        evidence_quality = _min_confidence(evidence_quality, "low")

    citation_audit = state.get("citation_audit") or []

    cited_claims = [
        c
        for c in citation_audit
        if c.get("citation_valid") is not None
    ]

    if cited_claims:
        unsupported = sum(
            1
            for c in citation_audit
            if c.get("support_level") == "unsupported"
        )

        unsupported_rate = unsupported / max(len(citation_audit), 1)

        if unsupported_rate > 0.15:
            answer_confidence = _min_confidence(answer_confidence, "medium")

        if unsupported_rate > 0.35:
            answer_confidence = _min_confidence(answer_confidence, "low")

    if state.get("verification_status") == "failed":
        answer_confidence = "low"
        evidence_quality = _min_confidence(evidence_quality, "low")
        dc["explanation"] = (
            (dc.get("explanation") or "")
            + " Confidence reduced: claim verification failed."
        )
    elif state.get("verification_status") == "passed_heuristic":
        answer_confidence = _min_confidence(answer_confidence, "medium")
        evidence_quality = _min_confidence(evidence_quality, "medium")
        dc["explanation"] = (
            (dc.get("explanation") or "")
            + " Confidence capped: claim verification used a heuristic "
            "fallback rather than full LLM review."
        )

    if epistemic_report:
        if epistemic_report.get("unsupported_quantitative_claims", 0) >= 1:
            answer_confidence = _min_confidence(answer_confidence, "low")
            evidence_quality = _min_confidence(evidence_quality, "medium")
            dc["explanation"] = (
                (dc.get("explanation") or "")
                + " Confidence reduced: quantitative claims lack source support."
            )
        if epistemic_report.get("fabricated_numbers", 0) >= 1:
            answer_confidence = _min_confidence(answer_confidence, "low")
            dc["explanation"] = (
                (dc.get("explanation") or "")
                + " Confidence reduced: numbers found that no source contains."
            )
        if epistemic_report.get("abstention_rewarded"):
            dc["explanation"] = (
                (dc.get("explanation") or "")
                + " Honest abstention on unknowns was credited, not penalized."
            )
        
    dc["answer_confidence"] = answer_confidence
    dc["evidence_quality"] = evidence_quality


    if not dc.get("explanation"):
        dc["explanation"] = "Confidence adjusted by claim/citation verification."

    return dc


def _enrich_references(
    references: list[dict],
    papers: list[dict],
    citation_audit: list[dict],
) -> list[dict]:
    if not references:
        return references

    from app.services.reference_builder import paper_id_to_ref_id_map

    id_map = paper_id_to_ref_id_map(papers, references)

    ref_to_paper = {
        int(rid): int(pid)
        for pid, rid in id_map.items()
    }

    paper_notes: dict[int, dict] = {}

    for audit in citation_audit:
        pid = audit.get("corrected_citation_paper_id")

        if pid is None:
            continue

        reason = audit.get("reason") or ""
        support = audit.get("support_level") or ""

        if not reason and not support:
            continue

        current = paper_notes.setdefault(int(pid), {})

        if reason and not current.get("why_cited"):
            current["why_cited"] = reason

        if support and not current.get("support_level"):
            current["support_level"] = support

    enriched = []

    for r in references:
        r = dict(r)

        pid = ref_to_paper.get(int(r.get("id")))

        if pid is not None and pid in paper_notes:
            r["why_cited"] = (
                r.get("why_cited")
                or paper_notes[pid].get("why_cited")
            )
            r["support_level"] = (
                r.get("support_level")
                or paper_notes[pid].get("support_level")
            )

        if r.get("source_role") is None:
            role = (
                papers[int(pid)].get("_source_role")
                if pid is not None and 0 <= int(pid) < len(papers)
                else None
            )
            r["source_role"] = role

        enriched.append(r)

    return enriched


def verify_answer_node(state: AgentState) -> AgentState:
    draft = state.get("final_answer") or ""
    papers = state.get("ranked_papers") or []
    answer_spec = state.get("answer_spec") or {}

    verification_status = "not_run"

    if not draft:
        return {
            "citation_audit": [],
            "math_verification": None,
            "primary_source_present": False,
            "verification_status": "not_run",
        }

    math_required = bool(answer_spec.get("equation_verification_required"))
    with ThreadPoolExecutor(max_workers=2) as ex:
        math_future = (
            ex.submit(_math_verify_llm, state, draft, answer_spec)
            if math_required
            else None
        )
        llm_claims = _extract_claims_llm(state, draft)
        pre_math = math_future.result() if math_future else None
    claims_extraction_failed = llm_claims is None
    claims_source = "deterministic" if claims_extraction_failed else "llm"

    claims = llm_claims if llm_claims else _extract_claims_deterministic(draft)

    if not claims:
        verification_status = (
            "unavailable" if claims_extraction_failed else "partial"
        )
    elif claims_extraction_failed:
        verification_status = "passed_heuristic"
    else:
        verification_status = "passed"

    llm_audits = _audit_claims_llm(state, claims, papers)
    audits_extraction_failed = llm_audits is None
    audits_source = "deterministic" if audits_extraction_failed else "llm"

    audits = llm_audits if llm_audits is not None else []

    fallback_audits = _audit_claims_deterministic(claims, papers)

    if not audits and fallback_audits:
        audits = fallback_audits
    else:
        by_claim = {
            a.get("claim_id"): a
            for a in audits
        }

        missing = [
            a
            for a in fallback_audits
            if a.get("claim_id") not in by_claim
        ]

        audits.extend(missing)
    ledger = state.get("reasoning_ledger") or {}
    epistemic_report = _build_epistemic_report(
        claims,
        audits,
        draft,
        papers,
        ledger,
        state.get("coverage_gaps") or [],
    )

    if claims and not audits:
        verification_status = "unavailable"
    elif verification_status == "passed" and audits_extraction_failed:
        verification_status = "passed_heuristic"

    primary_source_present = _primary_source_present(
        claims,
        audits,
        papers,
        answer_spec,
    )

    if verification_status in ("passed", "passed_heuristic"):
        critical_defect = False
        partial_finding = False

        primary_papers = {
            i
            for i, p in enumerate(papers)
            if p.get("_primary_candidate")
            or p.get("_source_role") == "primary"
        }

        audit_by_claim = {
            a.get("claim_id"): a
            for a in audits
        }

        for claim in claims:
            audit = audit_by_claim.get(claim.get("id")) or {}

            unsupported = (
                audit.get("citation_valid") is False
                or audit.get("support_level") == "unsupported"
            )

            if not unsupported and not claim.get("requires_primary_source"):
                continue

            if claim.get("requires_primary_source"):
                cited = [
                    i
                    for i in claim.get("cited_paper_ids", [])
                    if isinstance(i, int)
                ]

                corrected = audit.get("corrected_citation_paper_id")

                has_primary = any(
                    i in primary_papers
                    for i in cited
                ) or (
                    isinstance(corrected, int)
                    and corrected in primary_papers
                )

                if unsupported or not has_primary:
                    critical_defect = True
            else:
                partial_finding = True

        if (
            epistemic_report["unsupported_quantitative_claims"] >= 2
            or epistemic_report["fabricated_numbers"] >= 2
        ):
            critical_defect = True
        elif (
            epistemic_report["unsupported_quantitative_claims"] == 1
            or epistemic_report["fabricated_numbers"] == 1
        ) and not critical_defect:
            partial_finding = True

        if critical_defect:
            verification_status = "failed"
        elif partial_finding:
            verification_status = "partial"

    math_verification = None
    if math_required:
        math_verification = (
            pre_math
            if pre_math is not None
            else _math_verify_deterministic(answer_spec)
        )
        if math_verification.get("critical_math_failed"):
            verification_status = "failed"
        elif "VERIFICATION_SKIPPED" in str(
            math_verification.get("notes", "")
        ).upper():
            if verification_status != "failed":
                verification_status = "partial"

    references = _enrich_references(
        state.get("references") or [],
        papers,
        audits,
    )

    rels = []

    for p in papers[:6]:
        r = float(
            p.get("_relevance_orig")
            or p.get("_initial_sim")
            or p.get("final_score")
            or p.get("score")
            or 0.0
        )
        rels.append(r)

    avg_rel = sum(rels) / len(rels) if rels else 0.0

    dynamic_confidence = _apply_confidence_caps(
        state.get("dynamic_confidence") or {},
        avg_rel,
        {
            **state,
            "primary_source_present": primary_source_present,
            "verification_status": verification_status,
        },
        epistemic_report,
    )

    print(
        f"[verify] {len(claims)} claims ({claims_source}), "
        f"{len(audits)} audits ({audits_source}), "
        f"math={'yes' if math_verification else 'no'}, "
        f"primary={primary_source_present}, "
        f"status={verification_status}"
    )

    return {
        "citation_audit": audits,
        "math_verification": math_verification,
        "primary_source_present": primary_source_present,
        "references": references,
        "dynamic_confidence": dynamic_confidence,
        "verification_status": verification_status,
        "claims_source": claims_source,
        "audits_source": audits_source,
        "epistemic_report": epistemic_report,
    }