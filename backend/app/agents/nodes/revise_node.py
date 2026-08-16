import re

from langchain_core.messages import SystemMessage, HumanMessage

from app.agents.state import AgentState
from app.services.llm_client import get_llm
from app.config import settings


QUALITY_RULES = """
Do NOT remove or alter existing citation markers like [1], [2], or [paper_id=N].
Do NOT invent new citations. Only cite paper_ids present in AVAILABLE SOURCES.
If the gap exists because the literature does not cover it, say so explicitly
with a clear limitation sentence rather than filling it with speculation.
Preserve the existing markdown structure (headings, tables, bullet lists).
Do NOT repeat facts, numbers, or arguments already present elsewhere in the report.
NEVER invent numbers, dates, costs, or statistics to fill a gap. If a required
figure is missing from the sources, state that it is UNKNOWN or give the
formula/inputs needed to derive it.
"""


REVISE_TIMEOUT = getattr(settings, "REPORT_REVISE_TIMEOUT", 30)


def _looks_like_provider_quota_error(e: Exception) -> bool:
    msg = str(e).lower()

    return (
        "rate limit" in msg
        or "rate_limit" in msg
        or "429" in msg
        or "quota" in msg
        or "tpd" in msg
        or "tpm" in msg
        or "capacity" in msg
        or "too many requests" in msg
    )


def _revision_context(state: AgentState) -> str:
    lines = []

    math_verification = state.get("math_verification") or {}
    equations = math_verification.get("checked_equations") or []

    for eq in equations:
        if isinstance(eq, dict) and eq.get("is_correct") is False:
            lines.append(
                f"- Equation issue: '{eq.get('original_text', '')}' -> "
                f"corrected form: '{eq.get('corrected_form') or eq.get('canonical_form') or '(not provided)'}'"
            )

    if math_verification.get("critical_math_failed"):
        lines.append("- Math verification failed critically; fix the equations.")

    citation_audit = state.get("citation_audit") or []

    for c in citation_audit:
        if isinstance(c, dict) and not c.get("citation_valid"):
            lines.append(
                f"- Unsupported citation for claim '{c.get('claim_text', '')}': {c.get('reason', '')}"
            )

    answer_spec = state.get("answer_spec") or {}
    nongoals = answer_spec.get("non_goals") or []

    if nongoals:
        lines.append(
            "- Remove content about non-goals: "
            + "; ".join(str(g) for g in nongoals)
        )

    return "\n".join(lines) if lines else "- none"


def _extract_missing_items(instruction: str) -> tuple[str, list[str]]:
    """
    Pull the list of missing items out of a critique instruction, and
    classify them as either whole missing MODULES or missing COMPONENTS.
    """
    patterns = [
        (r"missing modules?:\s*(.+?)(?:\.\s|\.$|$)", "modules"),
        (
            r"required (?:components?|elements?) missing:\s*(.+?)(?:\.\s|\.$|$)",
            "components",
        ),
        (
            r"missing (?:components?|elements?):\s*(.+?)(?:\.\s|\.$|$)",
            "components",
        ),
    ]

    for pattern, kind in patterns:
        m = re.search(pattern, instruction, re.IGNORECASE)

        if not m:
            continue

        raw_list = m.group(1)

        delimiter = ";" if ";" in raw_list else ","

        items = []
        for part in raw_list.split(delimiter):
            t = part.strip().strip(".")
            if t and len(t) > 2:
                items.append(t)

        if items:
            return kind, items

    return "", []


def _extract_missing_module_titles(instruction: str) -> list[str]:
    """Backward-compatible wrapper: only returns whole-module gaps."""
    kind, items = _extract_missing_items(instruction)
    return items if kind == "modules" else []


def _redo_specific_sections(
    state: AgentState,
    redo_ids: list[str],
    instruction: str,
) -> dict:
    """
    Regenerate ONLY the flagged sections, splice them back.
    """
    section_outputs = state.get("section_outputs") or []
    papers = state.get("ranked_papers", [])
    plan = state.get("report_plan") or {}

    redo_titles = [
        s.get("title", s.get("module_id", ""))
        for s in section_outputs
        if s.get("module_id") in redo_ids
    ]

    if not redo_titles:
        return {"needs_revision": False}

    paper_block = "\n\n".join(
        f"[paper_id={i}] {p.get('title', '')}: {(p.get('summary') or '')[:400]}"
        for i, p in enumerate(papers[:6])
    )

    prompt = f"""Rewrite ONLY these sections of a research report.

USER QUERY:
{state.get('query', '')}

SECTIONS TO REWRITE:
{', '.join(redo_titles)}

REASON:
{instruction}

AVAILABLE SOURCES:
{paper_block or '(no sources)'}

Rules:
Start each section with a ## heading matching its title.
Keep each section to 150–350 words.
Cite sources as [paper_id=N].
Do NOT invent numbers or citations.
Return markdown only.
"""

    try:
        llm = get_llm(temperature=0, task="strong")

        response = llm.invoke(
            [
                SystemMessage(
                    content=(
                        "Rewrite only the requested sections. "
                        "Markdown only."
                    )
                ),
                HumanMessage(content=prompt),
            ],
            config={"timeout": REVISE_TIMEOUT},
        )

        new_content = response.content.strip()

        if len(new_content) < 80:
            return {"needs_revision": False}

        from app.services.reference_builder import extract_paper_ids
        from app.agents.summarize_node import _merge_sections, _clean_content
        from app.agents.report_modules import get_disclaimer

        for s in section_outputs:
            if s.get("module_id") not in redo_ids:
                continue

            title = s.get("title", "")

            if not title:
                continue

            pattern = rf"##\s+{re.escape(title)}\s*\n(.*?)(?=\n##\s|\Z)"
            match = re.search(pattern, new_content, re.DOTALL)

            if match:
                s["content"] = _clean_content(match.group(1).strip())
                s["cited_paper_ids"] = extract_paper_ids(s["content"])

        new_answer = _merge_sections(section_outputs, plan).strip()

        disclaimer = get_disclaimer()

        if disclaimer and disclaimer not in new_answer:
            new_answer = new_answer.rstrip() + "\n\n---\n\n*" + disclaimer + "*"

        cited = set()

        for s in section_outputs:
            for pid in s.get("cited_paper_ids", []):
                cited.add(str(pid))

        valid_cited = sorted(
            cited,
            key=lambda x: int(x) if x.isdigit() else 999999,
        )

        return {
            "final_answer": new_answer,
            "section_outputs": section_outputs,
            "needs_revision": False,
            "cited_paper_ids": valid_cited,
        }

    except Exception as e:
        print(f"[revise_node] section redo failed: {type(e).__name__}: {e}")
        return {"needs_revision": False}


def revise_node(state: AgentState) -> AgentState:
    if not state.get("needs_revision"):
        return {"needs_revision": False}

    if state.get("verification_status") == "unavailable":
        return {"needs_revision": False}

    draft = state.get("final_answer", "")
    instruction = state.get("revision_instruction", "")

    if not draft or not instruction:
        return {"needs_revision": False}

    redo_ids = state.get("revision_section_ids") or []

    if redo_ids:
        return _redo_specific_sections(state, redo_ids, instruction)

    ref_marker = "\n\n---\n\n**References**"

    if ref_marker in draft:
        body, refs_block = draft.split(ref_marker, 1)
        refs_block = ref_marker + refs_block
    else:
        body = draft
        refs_block = ""

    missing_kind, missing_items = _extract_missing_items(instruction)

    llm = get_llm(temperature=0, task="strong")

    if missing_kind == "modules" and missing_items:
        papers = state.get("ranked_papers", [])

        paper_block = "\n\n".join(
            f"[{i}] {p.get('title', '')}: {(p.get('summary') or '')[:400]}"
            for i, p in enumerate(papers[:6])
        )

        sections_prompt = f"""
You are adding missing sections to an existing research report.

USER QUERY:
{state.get('query', '')}

EXISTING REPORT (do NOT rewrite this, it is already written in full below):
{body}

AVAILABLE SOURCES:
{paper_block or "(no sources)"}

WRITE ONLY THESE MISSING SECTIONS:
{chr(10).join(f'- {t}' for t in missing_items)}

RULES:
Start each section with a ## heading matching its title.
Keep each section to 150-300 words.
Do NOT rewrite or summarize the existing report.
{QUALITY_RULES}

Return markdown only. No JSON.
""".strip()

        try:
            response = llm.invoke(
                [
                    SystemMessage(
                        content=(
                            "You add missing sections to research reports. "
                            "Return markdown only."
                        )
                    ),
                    HumanMessage(content=sections_prompt),
                ],
                config={"timeout": REVISE_TIMEOUT},
            )

            new_sections = response.content.strip()

            if new_sections and len(new_sections) > 100:
                revised = body.rstrip() + "\n\n" + new_sections + refs_block

                print(
                    f"[revise_node] targeted path succeeded ({len(missing_items)} sections)"
                )

                return {
                    "final_answer": revised,
                    "needs_revision": False,
                }

            print(
                "[revise_node] targeted path returned too little content, falling back"
            )

        except Exception as e:
            print(
                f"[revise_node] targeted path failed: {type(e).__name__}: {e}"
            )

            if _looks_like_provider_quota_error(e):
                print(
                    "[revise_node] provider quota/rate limit detected; keeping original answer"
                )
                return {"needs_revision": False}

    elif missing_kind == "components" and missing_items:
        papers = state.get("ranked_papers", [])

        paper_block = "\n\n".join(
            f"[{i}] {p.get('title', '')}: {(p.get('summary') or '')[:400]}"
            for i, p in enumerate(papers[:6])
        )

        components_prompt = f"""
You are patching specific missing content into an existing research report.
The report structure is already correct -- do NOT add new top-level headings.

USER QUERY:
{state.get('query', '')}

EXISTING REPORT (revise in place, return the FULL report body):
{body}

AVAILABLE SOURCES:
{paper_block or "(no sources)"}

THESE SPECIFIC COMPONENTS ARE MISSING AND MUST BE ADDED TO THE RELEVANT
EXISTING SECTION (not as new headings, but woven into the section that
already discusses this topic, e.g. into "Derivation" or "Architecture"):
{chr(10).join(f'- {t}' for t in missing_items)}

RULES:
For each missing component, find the section where it belongs and insert
a properly explained treatment of it there.
Keep all other existing content and section headings unchanged.
Do NOT create new top-level sections for these items.
{QUALITY_RULES}

Return the full revised report body only. No JSON, no commentary.
""".strip()

        try:
            response = llm.invoke(
                [
                    SystemMessage(
                        content=(
                            "You patch specific missing content into existing "
                            "research report sections. Return the full revised "
                            "body only."
                        )
                    ),
                    HumanMessage(content=components_prompt),
                ],
                config={"timeout": REVISE_TIMEOUT},
            )

            patched = response.content.strip()

            if ref_marker in patched:
                patched = patched.split(ref_marker, 1)[0].rstrip()

            if patched and len(patched) >= max(200, int(len(body) * 0.5)):
                print(
                    f"[revise_node] targeted component-patch path succeeded "
                    f"({len(missing_items)} components)"
                )

                return {
                    "final_answer": patched + refs_block,
                    "needs_revision": False,
                }

            print(
                "[revise_node] component-patch path returned too little content, falling back"
            )

        except Exception as e:
            print(
                f"[revise_node] component-patch path failed: {type(e).__name__}: {e}"
            )

            if _looks_like_provider_quota_error(e):
                print(
                    "[revise_node] provider quota/rate limit detected; keeping original answer"
                )
                return {"needs_revision": False}

    prompt = f"""Revise this answer to fix ONE specific gap.

GAP TO FIX:
{instruction}

REVISION CONTEXT:
{_revision_context(state)}

CURRENT ANSWER:
{body}

Rules:
Make the minimal edit needed. Add 2-4 sentences or one short paragraph,
or a full section only if the gap genuinely requires one.

Fix equations to their canonical form using sqrt(d_k) style scaling terms
(never drop a square root or a normalization term).

Replace an unsupported citation with the paper that actually supports the claim,
or drop the citation and label the claim unsupported.

Remove content that the answer specification marks as a non-goal.

Do NOT rewrite sections that are already fine.
{QUALITY_RULES}

Return the full revised answer body only.
"""

    try:
        response = llm.invoke(
            [
                SystemMessage(
                    content=(
                        "You make minimal, targeted edits to research answers. "
                        "Return the full revised text only."
                    )
                ),
                HumanMessage(content=prompt),
            ],
            config={"timeout": REVISE_TIMEOUT},
        )

        revised = response.content.strip()

        if ref_marker in revised:
            revised = revised.split(ref_marker, 1)[0].rstrip()

        if len(revised) < max(200, int(len(body) * 0.25)):
            print(
                "[revise_node] fallback path returned suspiciously short output, keeping original"
            )
            return {"needs_revision": False}

        print("[revise_node] fallback path used")

        return {
            "final_answer": revised + refs_block,
            "needs_revision": False,
        }

    except Exception as e:
        print(
            f"[revise_node] fallback path failed, keeping original: {type(e).__name__}: {e}"
        )

        if _looks_like_provider_quota_error(e):
            print(
                "[revise_node] provider quota/rate limit detected; keeping original answer"
            )

        return {"needs_revision": False}