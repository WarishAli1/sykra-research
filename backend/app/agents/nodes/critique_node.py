import re
import json

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.state import AgentState
from app.services.llm_client import get_llm
from app.config import settings


_MAX_REVISIONS = 1
_MIN_MODULES_FOR_CRITIQUE = 1


_SECTION_CRITIQUE_PROMPT = """You are a quality checker for a research report.

Compare the draft sections against the user's original question.

USER QUESTION:
{query}

DRAFT SECTIONS:
{sections_block}

For each section, decide:
1. Does it correctly and sufficiently address its part of the question?
2. Is it factually grounded in the cited sources?
3. Does it contain obvious hallucinations or unsupported claims?

Return a JSON object:
{{
  "pass": true/false,
  "sections_to_redo": ["module_id_1", ...],
  "reason": "brief explanation"
}}

Only set pass=false and list sections_to_redo if a section is genuinely wrong, missing critical content, or hallucinating.

Do NOT flag style, length, or minor wording issues.
"""


def _extract_json_object(text: str) -> dict:
    text = (text or "").strip()

    text = re.sub(
        r"^```(?:json)?\s*|\s*```$",
        "",
        text,
        flags=re.MULTILINE,
    )

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}

    try:
        return json.loads(match.group(0))
    except Exception:
        return {}


def _normalize_component(text: str) -> str:
    text = str(text or "").lower().replace("-", " ")
    text = re.sub(r"[^\w\s-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def component_appears_in_answer(component: str, answer: str) -> bool:
    comp = _normalize_component(component)
    ans = _normalize_component(answer)

    if not comp:
        return True

    if comp in ans:
        return True

    tokens = [
        token
        for token in comp.split()
        if len(token) >= 4
    ]

    if not tokens:
        return True

    if len(tokens) == 1:
        return tokens[0] in ans

    hits = sum(
        1
        for token in tokens
        if token in ans
    )

    return hits >= len(tokens) * 0.6


def _paper_year(paper: dict) -> int | None:
    for key in ("published", "publication_year", "year"):
        value = paper.get(key)
        if value is None:
            continue

        match = re.search(r"\b(19|20)\d{2}\b", str(value))
        if match:
            return int(match.group(0))

    return None


def _study_type_matches(paper: dict, required_type: str) -> bool:
    blob = " ".join(
        [
            str(paper.get("title") or ""),
            str(paper.get("summary") or ""),
            str(paper.get("study_type") or ""),
            str(paper.get("type") or ""),
            str(paper.get("venue") or ""),
        ]
    ).lower()

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
        return any(re.search(p, blob) for p in patterns)

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


def _check_evidence_sufficiency(state: AgentState) -> dict:
    evidence_contract = state.get("evidence_contract") or {}
    eligible = state.get("eligible_papers") or []
    ranked = state.get("ranked_papers") or []

    required_count = evidence_contract.get("minimum_evidence_count", 3)

    eligible_count = len(eligible) if eligible else len(ranked)

    hard_constraints = [
        c
        for c in evidence_contract.get("constraints", [])
        if c.get("strength") == "hard"
    ]

    satisfied = 0
    gaps = []

    for c in hard_constraints:
        field = c.get("field", "")
        value = c.get("value")
        found = False

        for p in (eligible or ranked)[:10]:
            if field == "publication_year":
                year = _paper_year(p)
                if year is None:
                    continue

                try:
                    required_year = int(value)
                except Exception:
                    continue

                if c.get("operator") == "gte" and year >= required_year:
                    found = True
                    break

                if c.get("operator") == "lte" and year <= required_year:
                    found = True
                    break

            elif field == "study_type":
                if _study_type_matches(p, str(value)):
                    found = True
                    break

        if found:
            satisfied += 1
        else:
            gaps.append(
                f"No evidence satisfies: {field} {c.get('operator')} {value}"
            )

    coverage = (
        satisfied / len(hard_constraints)
        if hard_constraints
        else 1.0
    )

    threshold = getattr(
        settings,
        "EVIDENCE_SUFFICIENCY_THRESHOLD",
        0.60,
    )

    warning_threshold = getattr(
        settings,
        "EVIDENCE_SUFFICIENCY_WARNING_THRESHOLD",
        0.85,
    )

    sufficient = (
        eligible_count >= required_count
        and coverage >= threshold
    )

    if coverage >= warning_threshold:
        recommendation = "proceed"
    elif coverage >= threshold:
        recommendation = "proceed_with_warning"
    elif eligible_count < required_count:
        recommendation = "expand_search"
        gaps.append(
            f"Only {eligible_count} eligible papers found, "
            f"need {required_count}"
        )
    else:
        recommendation = "abstain"

    return {
        "eligible_papers": eligible_count,
        "required_papers": required_count,
        "contract_coverage": round(coverage, 2),
        "sufficient": sufficient,
        "gaps": gaps,
        "recommendation": recommendation,
    }


def critique_node(state: AgentState) -> AgentState:
    depth = state.get("report_depth")

    if not depth:
        response_mode = state.get("response_mode", "normal")
        depth = (
            "high"
            if response_mode in ("researched", "graph_research")
            else "low"
        )

    if depth == "low":
        return {"needs_revision": False}

    if depth == "medium" and state.get("response_mode", "normal") == "normal":
        return {"needs_revision": False}

    revisions_done = state.get("revision_count", 0)

    if revisions_done >= _MAX_REVISIONS:
        return {"needs_revision": False}

    hard_failures = []

    epistemic_report = state.get("epistemic_report") or {}

    if epistemic_report.get("unsupported_quantitative_claims", 0) >= 2:
        hard_failures.append(
            "Quantitative claims lack source support: remove invented figures "
            "or label them Inference:/Estimate: with stated assumptions."
        )

    if epistemic_report.get("fabricated_numbers", 0) >= 2:
        hard_failures.append(
            "Numbers appear in the answer that no retrieved source contains: "
            "verify them against sources or remove them."
        )

    answer_spec = state.get("answer_spec") or {}

    if answer_spec.get("primary_source_required"):
        if not any(
            p.get("_primary_candidate")
            or (p.get("_primary_source_score") or 0) > 0.8
            for p in state.get("ranked_papers", [])
        ):
            hard_failures.append(
                "Primary source required but not confidently retrieved."
            )

    math_verification = state.get("math_verification") or {}

    if math_verification.get("critical_math_failed"):
        hard_failures.append("Critical equation failed verification.")

    citation_audit = state.get("citation_audit") or []

    unsupported_citations = [
        c
        for c in citation_audit
        if not c.get("citation_valid")
    ]

    if len(unsupported_citations) > max(1, len(citation_audit) // 5):
        hard_failures.append("Too many citations do not support their claims.")

    required_components = answer_spec.get("expected_components", [])

    missing_components = [
        c
        for c in required_components
        if not component_appears_in_answer(
            c,
            state.get("final_answer", ""),
        )
    ]

    if missing_components:
        hard_failures.append(
            "Required components missing: " + ", ".join(missing_components)
        )

    if hard_failures:
        print(f"[critique_node] hard failures: {hard_failures}")
        return {
            "needs_revision": True,
            "revision_instruction": " ".join(hard_failures),
            "revision_count": revisions_done + 1,
            "revision_section_ids": [],
        }

    sufficiency = _check_evidence_sufficiency(state)

    if sufficiency["recommendation"] == "abstain":
        return {
            "needs_revision": True,
            "revision_instruction": (
                "Evidence sufficiency gate failed: insufficient eligible evidence. "
                "Gaps: " + "; ".join(sufficiency["gaps"][:3])
            ),
            "revision_count": revisions_done + 1,
            "revision_section_ids": [],
        }

    draft = state.get("final_answer", "")
    query = state.get("query", "")

    if not draft or not query or len(draft.strip()) < 250:
        return {"needs_revision": False}

    plan = state.get("report_plan") or {}
    section_outputs = state.get("section_outputs") or []

    generative_module_count = sum(
        1
        for m in plan.get("modules", [])
        if m.get("module_id") not in ("references",)
    )

    if generative_module_count < _MIN_MODULES_FOR_CRITIQUE:
        return {"needs_revision": False}

    if not section_outputs:
        return {"needs_revision": False}

    sections_block = "\n\n".join(
        f"### {s.get('title', s.get('module_id', ''))}\n"
        f"{s.get('content', '')[:1500]}"
        for s in section_outputs
        if s.get("module_id") != "references"
    )

    llm = get_llm(temperature=0, task="fast")

    try:
        raw = llm.invoke(
            [
                SystemMessage(
                    content=(
                        "You are a section-level quality checker. "
                        "Return JSON only."
                    )
                ),
                HumanMessage(
                    content=_SECTION_CRITIQUE_PROMPT.format(
                        query=query,
                        sections_block=sections_block[:6000],
                    )
                ),
            ],
            config={"timeout": settings.REPORT_CRITIQUE_TIMEOUT},
        )

        result = _extract_json_object(raw.content)

        if not result:
            return {"needs_revision": False}

    except Exception as e:
        print(f"[critique_node] section critique failed: {type(e).__name__}: {e}")
        return {"needs_revision": False}

    if result.get("pass", True):
        return {"needs_revision": False}

    raw_redo_ids = result.get("sections_to_redo", [])

    valid_module_ids = {
        s.get("module_id")
        for s in section_outputs
        if s.get("module_id")
    }

    redo_ids = [
        mid
        for mid in raw_redo_ids
        if mid in valid_module_ids
    ]

    if not redo_ids:
        return {"needs_revision": False}

    instruction = (
        f"Redo these sections: {', '.join(redo_ids)}. "
        f"Reason: {result.get('reason', 'insufficient coverage')}"
    )

    print(f"[critique_node] sections to redo: {redo_ids}")

    return {
        "needs_revision": True,
        "revision_instruction": instruction,
        "revision_count": revisions_done + 1,
        "revision_section_ids": redo_ids,
    }