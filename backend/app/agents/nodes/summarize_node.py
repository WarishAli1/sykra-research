import re
import json
import difflib
import threading

from concurrent.futures import ThreadPoolExecutor, as_completed

from langchain_core.messages import SystemMessage, HumanMessage

from app.agents.state import AgentState
from app.agents.schemas import SectionBatch, SectionOutput

from app.services.llm_client import get_llm

from app.services.reference_builder import (
    build_references,
    paper_id_to_ref_id_map,
    rewrite_inline_citations,
    format_reference_block,
    extract_paper_ids,
)

from app.agents.report_modules import default_report_plan, MODULE_LIBRARY
from app.utils.text_sanitizer import sanitize_for_web
from app.services.sse import bridge_push
from app.config import settings


llm = get_llm(temperature=0, task="default")


FORMAT_INSTRUCTION = """
MATH FORMATTING:
Use LaTeX delimiters for formulas.
Inline math: $x$.
Display math MUST be on its own lines with EMPTY blank lines above and below it:

$$
y = mx + b
$$

Never mash display math into the middle of a text paragraph. Always leave a blank line before and after the $$ block.

Define every symbol in prose the first time it appears. Use the exact standard form
established in the canonical/original source for the topic — do not approximate or
simplify a formula (e.g. do not drop a square root, substitute the wrong dimension
variable, or omit a normalization term).

CURRENCY RULE:
Never use the $ symbol for currency amounts.
Write "USD 48/MWh" or "48 USD/MWh" instead of "$48/MWh".

CITATION RULE:
Use ONLY ASCII square brackets for citations: [paper_id=N].
Never use fullwidth brackets like 【paper_id=N】.
Never combine multiple ids in one bracket like [paper_id=0, paper_id=1]. Cite each
source in its own bracket: [paper_id=0][paper_id=1].

QUANTITATIVE & CITATION INTEGRITY (CRITICAL):
1. NUMERICAL GROUNDING: Never invent specific numbers, dollar amounts, percentages, or dates. Use ONLY figures present in the REASONING LEDGER. If a required figure is listed under UNSUPPORTED VARIABLES, do not guess it — state that it is unknown, or describe the formula/inputs needed to derive it, or prefix an estimate with "Inference:".
2. CITATION LAUNDERING BAN: Never cite a paper by analogy (e.g. "this health-systems finding applies to energy"). If a retrieved source does not directly study the query's domain, do not cite it for domain claims.
3. INTERNAL CONSISTENCY: If you define strategies, scenarios, or categories, use the exact same names throughout. Do not rename them mid-report.
4. SCENARIO DISCIPLINE: If a scenario matrix is provided, answer resilience/robustness questions by referencing specific scenario rows, not by asserting a single option is "best" unconditionally.

Cite a source ONLY if it specifically supports the exact claim in that sentence.
Do not cite a paper just because it was retrieved — if a retrieved paper is not
directly relevant to what you are currently explaining, do not mention it at all.

Recent ≠ relevant. Do not introduce a paper's topic (e.g. a new attention variant,
a compression method, an unrelated domain application) unless the user's question
is actually about that topic.

INTEGRITY RULE:
Never write "a review of the literature was conducted," "the evidence was evaluated,"
"a systematic search was performed," or similar, unless describing something that
actually happened in this pipeline. If you are explaining a well-established concept
using one primary source, say so plainly — do not dress it up as a research review.
"""


class _OrderedSectionEmitter:
    """
    Holds completed sections and emits them strictly in plan order.

    If the analysis batch finishes a section early, it is held until
    all preceding core sections have been emitted.

    Thread-safe: two batch workers may call submit() concurrently.
    """

    def __init__(
        self,
        ordered_module_ids: list[str],
        request_id: str,
        cancel_check=None,
    ):
        self.order = ordered_module_ids
        self.request_id = request_id
        self.cancel_check = cancel_check

        self._ready: dict[str, str] = {}
        self._next = 0
        self._lock = threading.Lock()

    def submit(self, module_id: str, content: str) -> None:
        with self._lock:
            self._ready[module_id] = content
            self._flush_locked()

    def _flush_locked(self) -> None:
        while self._next < len(self.order):
            mid = self.order[self._next]

            if mid not in self._ready:
                break

            content = self._ready.pop(mid)
            self._next += 1

            if self.cancel_check and self.cancel_check():
                return

            bridge_push(self.request_id, ("section", mid, content))

    def flush_remaining(self) -> None:
        with self._lock:
            for mid in self.order[self._next:]:
                if mid in self._ready:
                    content = self._ready.pop(mid)
                    bridge_push(self.request_id, ("section", mid, content))

            self._next = len(self.order)


_MATH_DISPLAY_RE = re.compile(r"\$\$.*?\$\$", re.DOTALL)
_MATH_INLINE_RE = re.compile(r"\$[^$\n]+?\$")
_DEDUPE_LOCK = threading.Lock()


def _clean_content(text: str) -> str:
    if not text:
        return ""

    text = re.sub(
        r"(\$\$.*?\$\$)",
        r"\n\n\1\n\n",
        text,
        flags=re.DOTALL,
    )

    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def _sanitize_preserving_math(text: str) -> str:
    """
    Sanitize text while preserving LaTeX math blocks exactly.

    1. Replace LaTeX blocks with placeholders.
    2. Call sanitize_for_web().
    3. Restore original LaTeX blocks.
    """
    if not text:
        return ""

    math_blocks: list[str] = []

    def _stash(match):
        math_blocks.append(match.group(0))
        return f"@@MATH_BLOCK_{len(math_blocks) - 1}@@"

    protected = _MATH_DISPLAY_RE.sub(_stash, text)
    protected = _MATH_INLINE_RE.sub(_stash, protected)

    sanitized = sanitize_for_web(protected)

    for i, block in enumerate(math_blocks):
        sanitized = sanitized.replace(f"@@MATH_BLOCK_{i}@@", block)

    return sanitized


def _strip_headers(text: str) -> str:
    if not text:
        return text

    lines = text.split("\n")
    cleaned = []

    for line in lines:
        stripped = line.strip()

        if re.match(r"^#{1,4}\s+\S", stripped) and len(stripped) < 60:
            continue

        cleaned.append(line)

    return "\n".join(cleaned)


def _has_module(plan: dict, module_id: str) -> bool:
    return any(
        m.get("module_id") == module_id
        for m in plan.get("modules", [])
    )


def _important_query_terms(state: AgentState) -> list[str]:
    qu = state.get("query_understanding") or {}
    terms = set()

    q = state.get("query", "").lower()
    terms.update([w for w in re.split(r"[^a-z0-9+#.-]+", q) if len(w) > 3])

    for field in ("main_topic", "application_domain"):
        v = qu.get(field)
        if v:
            terms.add(v.lower().strip())

    for lst in ("methods_techniques", "entities", "academic_terminology"):
        for v in (qu.get(lst) or [])[:6]:
            if v:
                terms.add(v.lower().strip())

    for v in (qu.get("acronyms") or {}).values():
        if v:
            terms.add(v.lower().strip())

    return [t for t in terms if t]


def _fast_summaries(papers: list[dict], state: AgentState) -> dict[str, dict]:
    summaries = {}

    for i, p in enumerate(papers):
        score = float(
            p.get("final_score")
            or p.get("_relevance_orig")
            or p.get("_initial_sim")
            or p.get("score")
            or 0.0
        )

        if score >= 0.62:
            evidence_type = "direct"
        elif score >= 0.45:
            evidence_type = "supporting"
        else:
            evidence_type = "background"

        summaries[str(i)] = {
            "paper_id": str(i),
            "key_contribution": p.get("title", ""),
            "methodology": "",
            "findings": (p.get("summary") or p.get("text") or "")[:600],
            "relevance_to_query": "",
            "evidence_type": evidence_type,
            "key_metrics": [],
        }

    return summaries


def _match_module_header(title: str, batch_modules: list[dict]) -> dict | None:
    t = (title or "").strip().lower()

    if not t:
        return None

    for m in batch_modules:
        if t == m["title"].lower() or t == m["module_id"].replace("_", " "):
            return m

    for m in batch_modules:
        mt = m["title"].lower()
        mid = m["module_id"].replace("_", " ")

        if mt in t or t in mt or mid in t or t in mid:
            return m

    names = [m["title"].lower() for m in batch_modules]

    close = difflib.get_close_matches(t, names, n=1, cutoff=0.6)

    if close:
        for m in batch_modules:
            if m["title"].lower() == close[0]:
                return m

    return None


def _build_paper_block(
    papers: list[dict],
    summaries: dict[str, dict],
    max_abstract: int = 700,
    max_papers: int = 8,
) -> str:
    parts = []

    for i, p in enumerate(papers[:max_papers]):
        s = summaries.get(str(i), {})

        if s:
            metrics = "; ".join((s.get("key_metrics") or [])[:4])

            parts.append(
                f"[paper_id={i}] [{s.get('evidence_type', 'supporting').upper()}] "
                f"Title: {p.get('title', '')}\n "
                f"Source: {p.get('source', '')}; Year: {p.get('published', '')}; "
                f"Citations: {p.get('citation_count', 0)}; Relevance: {p.get('_relevance_orig', p.get('_initial_sim', 0))}\n "
                f"Key contribution: {s.get('key_contribution', '')}\n "
                f"Findings: {s.get('findings', '')}\n "
                f"Metrics: {metrics}"
            )
        else:
            abstract = p.get("summary") or p.get("text") or ""

            parts.append(
                f"[paper_id={i}] Title: {p.get('title', '')}\n "
                f"Abstract: {abstract[:max_abstract]}"
            )

    return "\n\n".join(parts)


def _answer_spec_context(state: AgentState, evidence_matrix: dict) -> str:
    answer_spec = state.get("answer_spec") or {}
    lines = []

    outline = answer_spec.get("answer_outline") or []

    if outline:
        lines.append(
            "ANSWER OUTLINE:\n" + "\n".join(f"- {o}" for o in outline)
        )

    reqs = answer_spec.get("requirements") or []

    if reqs:
        req_lines = []

        for r in reqs[:12]:
            req_lines.append(
                f"- ({r.get('kind') or 'background'}, weight {r.get('weight') or 1}) {r.get('text') or ''}"
            )

        lines.append(
            "ANSWER REQUIREMENTS (a correct answer must address every high-weight requirement):\n"
            + "\n".join(req_lines)
        )

    nongoals = answer_spec.get("non_goals") or []

    if nongoals:
        lines.append(
            "NON-GOALS (do NOT spend answer space on these):\n"
            + "\n".join(f"- {g}" for g in nongoals)
        )

    expected_components = answer_spec.get("expected_components") or []

    if expected_components:
        lines.append(
            "REQUIRED COMPONENTS (the answer must explicitly contain and explain each listed component):\n"
            + "\n".join(f"- {c}" for c in expected_components)
        )

    eqs = answer_spec.get("expected_equations") or []

    if eqs:
        lines.append(
            "EXPECTED EQUATIONS (use canonical form; do not simplify or drop terms):\n"
            + "\n".join(f"- {e}" for e in eqs)
        )

    if evidence_matrix:
        lines.append(
            "EVIDENCE MATRIX (requirement -> support):\n"
            + json.dumps(evidence_matrix, indent=1)[:4500]
        )

    if answer_spec.get("primary_source_required"):
        lines.append(
            "PRIMARY-SOURCE DISCIPLINE: origin/historical/canonical claims must cite the original "
            "primary source. Do not cite a later interpretive paper for an original claim. "
            "If the primary source is missing, state that the claim relies on secondary evidence."
        )

    return "\n\n".join(lines)


def _matrix_status(paper_ids: list[int]) -> str:
    if not paper_ids:
        return "weak"

    if len(paper_ids) >= 2:
        return "strong"

    return "mixed"


def _build_evidence_matrix(
    state: AgentState,
    papers: list[dict],
    summaries: dict[str, dict],
    answer_spec: dict,
) -> dict[str, dict]:
    matrix: dict[str, dict] = {}

    def _paper_matches(idx: int, text: str) -> bool:
        if idx >= len(papers):
            return False

        ptext = " ".join(
            [
                papers[idx].get("title", ""),
                (papers[idx].get("summary") or "")[:1200],
            ]
        ).lower()

        tokens = [t for t in text.split(" ") if len(t) > 3]

        if not tokens:
            return text in ptext

        return sum(1 for t in tokens if t in ptext) >= max(2, int(len(tokens) * 0.6))

    def _support_for(text: str) -> tuple[list[int], list[str]]:
        paper_ids: list[int] = []
        roles: list[str] = []

        for sid, s in summaries.items():
            try:
                idx = int(sid)
            except (TypeError, ValueError):
                continue

            if not _paper_matches(idx, text):
                continue

            etype = s.get("evidence_type") or "supporting"

            if etype not in ("direct", "supporting"):
                continue

            paper_ids.append(idx)

            role = papers[idx].get("_source_role") or "secondary"

            if role not in roles:
                roles.append(role)

        return paper_ids[:5], roles[:5]

    for i, r in enumerate(answer_spec.get("requirements") or []):
        text = str(r.get("text") or "").strip()
        key = str(r.get("id") or "").strip() or f"requirement_{i}"

        if not text:
            matrix[key] = {
                "status": "weak",
                "paper_ids": [],
                "source_roles": [],
            }
            continue

        paper_ids, roles = _support_for(text)

        matrix[key] = {
            "status": _matrix_status(paper_ids),
            "paper_ids": paper_ids,
            "source_roles": roles,
        }

    for comp in answer_spec.get("expected_components") or []:
        ctext = str(comp).strip().lower().replace("_", " ")

        if not ctext:
            continue

        paper_ids, roles = _support_for(ctext)

        matrix[str(comp)] = {
            "status": _matrix_status(paper_ids),
            "paper_ids": paper_ids,
            "source_roles": roles,
        }

    for ng in answer_spec.get("non_goals") or []:
        matrix[str(ng)] = {
            "status": "not_required",
            "paper_ids": [],
            "source_roles": [],
        }

    return matrix


def _reclassify_evidence_types(
    papers: list[dict],
    summaries: dict,
    state: AgentState,
) -> dict:
    terms = _important_query_terms(state)

    direct_phrases = (
        "directly address",
        "directly study",
        "directly investigat",
        "proposes",
        "introduces",
        "presents",
        "framework for",
        "method for",
        "model for",
    )

    supporting_phrases = (
        "related",
        "similar",
        "applies",
        "uses",
        "dataset",
        "background",
        "supports",
    )

    for i, p in enumerate(papers):
        sid = str(i)

        s = summaries.get(sid) or {}

        rel = (s.get("relevance_to_query") or "").lower()
        contrib = (s.get("key_contribution") or "").lower()
        title = (p.get("title") or "").lower()

        text = f"{title} {contrib} {rel}"

        sim = float(
            p.get("_relevance_orig")
            or p.get("_initial_sim")
            or p.get("final_score")
            or p.get("score")
            or 0.0
        )

        term_hits = 0

        for t in terms:
            if not t:
                continue

            if t in title:
                term_hits += 2
            elif t in text:
                term_hits += 1

        if sim >= 0.62 or term_hits >= 4 or any(ph in rel for ph in direct_phrases):
            etype = "direct"
        elif sim >= 0.45 or term_hits >= 2 or any(ph in rel for ph in supporting_phrases):
            etype = "supporting"
        else:
            etype = "background"

        if p.get("_foundational_candidate") and sim >= 0.45 and etype == "background":
            etype = "supporting"

        s["evidence_type"] = etype
        summaries[sid] = s

    return summaries


def _count_evidence_types(summaries: dict) -> dict:
    counts = {
        "direct": 0,
        "supporting": 0,
        "background": 0,
    }

    for s in summaries.values():
        etype = (s.get("evidence_type") or "supporting").lower().strip()

        if etype not in counts:
            etype = "supporting"

        counts[etype] += 1

    return counts


def _status_from_paper_ids(paper_ids: list[str], summaries: dict) -> str:
    if not paper_ids:
        return "none"

    direct_count = 0
    supporting_count = 0

    for pid in paper_ids:
        etype = summaries.get(str(pid), {}).get("evidence_type", "background")

        if etype == "direct":
            direct_count += 1
        elif etype == "supporting":
            supporting_count += 1

    if direct_count >= 2 or (direct_count >= 1 and len(paper_ids) >= 3):
        return "strong"

    if direct_count >= 1 or len(paper_ids) >= 2:
        return "mixed"

    if supporting_count >= 1:
        return "weak"

    return "weak"


def _build_module_evidence_map(
    plan: dict,
    papers: list[dict],
    summaries: dict[str, dict],
    state: AgentState,
) -> dict[str, dict]:
    evidence_map = {}

    direct_ids = [
        sid
        for sid, s in summaries.items()
        if s.get("evidence_type") == "direct"
    ]

    supporting_ids = [
        sid
        for sid, s in summaries.items()
        if s.get("evidence_type") == "supporting"
    ]

    background_ids = [
        sid
        for sid, s in summaries.items()
        if s.get("evidence_type") == "background"
    ]

    understanding = state.get("query_understanding") or {}

    comparison_candidates = []

    comparison_candidates.extend(understanding.get("methods_techniques") or [])
    comparison_candidates.extend(understanding.get("entities") or [])

    comparison_candidates = list(
        dict.fromkeys([c.strip() for c in comparison_candidates if c and c.strip()])
    )

    keyword_map = {
        "risk_analysis": [
            "risk",
            "failure",
            "safety",
            "adverse",
            "side effect",
            "threat",
            "limitation",
        ],
        "tradeoffs": [
            "tradeoff",
            "trade-off",
            "pros",
            "cons",
            "advantage",
            "disadvantage",
            "comparison",
        ],
        "cost_resources": [
            "cost",
            "budget",
            "compute",
            "gpu",
            "memory",
            "latency",
            "resource",
            "price",
        ],
        "implementation_plan": [
            "implement",
            "deploy",
            "pipeline",
            "architecture",
            "build",
            "practice",
        ],
        "timeline_roadmap": [
            "roadmap",
            "timeline",
            "milestone",
            "phase",
            "future",
        ],
        "future_outlook": [
            "future",
            "forecast",
            "prediction",
            "trend",
            "outlook",
            "scenario",
        ],
        "alternatives": [
            "alternative",
            "baseline",
            "other",
            "approach",
            "method",
        ],
    }

    epistemic_mode = (state.get("report_plan") or {}).get(
        "epistemic_mode",
        "research_synthesis",
    )

    for module in plan.get("modules", []):
        mid = module.get("module_id")

        entry = {
            "module_id": mid,
            "evidence_status": "none",
            "paper_ids": [],
            "notes": "",
        }

        if epistemic_mode == "textbook_derivation" and mid in (
            "derivation",
            "key_concepts",
            "direct_answer",
        ):
            origin_ids = [
                sid
                for sid, s in summaries.items()
                if papers[int(sid)].get("_is_origin_paper")
            ]

            if not origin_ids:
                sorted_by_cites = sorted(
                    enumerate(papers),
                    key=lambda x: x[1].get("citation_count", 0),
                    reverse=True,
                )

                origin_ids = [str(i) for i, _ in sorted_by_cites[:2]]

            entry["paper_ids"] = origin_ids

            entry["evidence_status"] = _status_from_paper_ids(
                entry["paper_ids"],
                summaries,
            )

            entry["notes"] = (
                "LOCKED TO ORIGIN PAPERS. "
                "Do not cite recent variations or optimizations."
            )

        elif mid == "references":
            entry["evidence_status"] = "not_applicable"

        elif mid in ("background", "key_concepts"):
            entry["paper_ids"] = (
                background_ids + supporting_ids + direct_ids
            )[:4]

            entry["evidence_status"] = "not_applicable"

            entry["notes"] = (
                "Use background knowledge and retrieved context; "
                "cite only if directly useful."
            )

        elif mid == "comparative_analysis":
            entry["paper_ids"] = (direct_ids + supporting_ids)[:6]
            entry["evidence_status"] = _status_from_paper_ids(
                entry["paper_ids"], summaries,
            )
            if len(comparison_candidates) >= 2:
                entry["notes"] = (
                    f"Candidates: {', '.join(comparison_candidates[:6])}. "
                    "MANDATORY: Use a structured scenario matrix or sensitivity table if the query asks for trade-offs, resilience, or forecasting. "
                    "Define the strategies/scenarios ONCE and use consistent names throughout."
                )
            else:
                entry["notes"] = "Infer comparison items from the query and evidence."

        elif mid in ("research_findings", "methodology"):
            entry["paper_ids"] = (direct_ids + supporting_ids)[:6]

            entry["evidence_status"] = _status_from_paper_ids(
                entry["paper_ids"],
                summaries,
            )

        elif mid in keyword_map:
            matched = []

            kws = keyword_map[mid]

            for sid, s in summaries.items():
                text = " ".join(
                    [
                        str(s.get("key_contribution", "")),
                        str(s.get("findings", "")),
                        str(s.get("relevance_to_query", "")),
                    ]
                ).lower()

                if any(k in text for k in kws):
                    matched.append(sid)

            if matched:
                entry["paper_ids"] = matched[:6]
            else:
                entry["paper_ids"] = (direct_ids + supporting_ids)[:3]

            entry["evidence_status"] = _status_from_paper_ids(
                entry["paper_ids"],
                summaries,
            )

        else:
            entry["paper_ids"] = (
                direct_ids + supporting_ids + background_ids
            )[:5]

            entry["evidence_status"] = _status_from_paper_ids(
                entry["paper_ids"],
                summaries,
            )

        evidence_map[mid] = entry

    return evidence_map


def _evidence_mode_instruction(mode: str) -> str:
    if mode == "uploaded":
        return (
            "EVIDENCE MODE: UPLOADED DOCUMENT ONLY. "
            "Use only the uploaded document. Do not invent outside facts. "
            "If the document does not cover something, say so explicitly."
        )

    if mode == "blended":
        return (
            "EVIDENCE MODE: BLENDED. "
            "Treat uploaded documents as primary and retrieved literature as supporting/validation. "
            "Clearly separate document-derived claims from literature-derived claims."
        )

    return (
        "EVIDENCE MODE: LITERATURE. "
        "Use retrieved literature. Clearly distinguish evidence from inference."
    )


def _section_batch_prompt(
    batch_modules: list[dict],
    paper_block: str,
    state: AgentState,
    evidence_map: dict[str, dict],
    guardrails: list[str],
    plan: dict,
) -> str:
    module_lines = []

    for m in batch_modules:
        module_lines.append(
            f"- module_id: {m['module_id']}\n"
            f"  title: {m['title']}\n"
            f"  purpose: {m['purpose']}\n"
            f"  target_words: {m.get('target_words', 180)}\n"
            f"  evidence_policy: {m.get('evidence_policy', 'evidence_preferred')}"
        )

    evidence_lines = []

    for m in batch_modules:
        e = evidence_map.get(m["module_id"], {})

        evidence_lines.append(
            f"- {m['module_id']}: status={e.get('evidence_status', 'none')}, "
            f"allowed_paper_ids={','.join(e.get('paper_ids', [])[:6]) or 'none'}, "
            f"note={e.get('notes', '')}"
        )

    coverage = state.get("term_coverage") or {}

    coverage_lines = []

    for item in list(coverage.values())[:18]:
        coverage_lines.append(
            f"- need={item.get('need', '')} | status={item.get('status', 'unknown')} | "
            f"score={item.get('score', 0)} | evidence_ids={','.join(str(x) for x in item.get('evidence_ids', [])[:5]) or 'none'}"
        )

    if not coverage_lines:
        coverage_lines = ["- none"]

    guardrail_text = (
        "\n".join(f"- {g}" for g in guardrails)
        if guardrails
        else "- None"
    )

    batch_ids = {m["module_id"] for m in batch_modules}

    other_titles = [
        m.get("title", m.get("module_id", ""))
        for m in plan.get("modules", [])
        if m.get("module_id") not in batch_ids
        and m.get("module_id") not in ("references", "confidence_uncertainty")
    ]

    dedup_instruction = ""

    if other_titles:
        dedup_instruction = (
            f"\nOTHER SECTIONS IN THIS REPORT (do NOT repeat their content): "
            f"{', '.join(other_titles)}.\n"
            f"Each section must contain UNIQUE information. If a fact belongs in "
            f"another section, reference it briefly (e.g. 'as discussed in the "
            f"Comparative Analysis section') but do NOT restate numbers or arguments.\n"
        )

    dedup_instruction += (
        "\nREPETITION RULE:\n"
        "Do not repeat the same paragraph, equation, or explanation across modules.\n"
        "Each module must contain unique information.\n"
        "If another section already explains a concept, reference it briefly instead of restating it.\n"
    )

    epistemic_mode = (state.get("report_plan") or {}).get(
        "epistemic_mode",
        "research_synthesis",
    )

    epistemic_instructions = ""

    if epistemic_mode == "textbook_derivation":
        epistemic_instructions = """
EPISTEMIC MODE: TEXTBOOK DERIVATION & SYSTEM DEEP DIVE

You are writing a rigorous technical explanation of established mathematical or architectural foundations.

REPETITION BAN (CRITICAL):
The "Direct Answer" must be a brief 2-3 sentence summary stating the final canonical equation and its primary purpose. DO NOT put the full derivation here.
The "Derivation" section must contain the full, rigorous step-by-step mathematical proof.
DO NOT repeat the same equations, text, or explanations across different modules. Each module must contain strictly unique information.

CRITICAL DEPTH REQUIREMENT:
Do NOT be brief. The user expects a deep, detailed, and rigorous explanation.
Expand extensively on the "why" behind every mathematical operation, assumption, and architectural choice. Aim for 300-500 words per major section.


STRICT BANS:
NEVER write equations as plain text (e.g., NEVER write "A = softmax(Q K^T / d) V").
ALWAYS wrap inline math in `$` and display math in `$$` on its own line.
DO NOT write prose-heavy explanations like "We can parameterize the weights...". Use rigorous mathematical notation.

MANDATORY DERIVATION FORMAT:
Present derivations as sequential steps with one transformation per line.
For each step, explain why the transformation is valid.
Define dimensions/variables before use and keep notation consistent.
Keep each major equation in its own display block.

MANDATORY ARCHITECTURE/SYSTEM DEEP DIVE (If the query asks to explain a system, model, or architecture):
You MUST explicitly detail:
- Core Components: Break down the system into its fundamental building blocks.
- Data/Signal Flow: Explain how information flows through the system from input to output.
- Key Mechanisms: Explain the specific mechanisms that make the system work.
- Complexity: State the asymptotic time and space complexity (Big-O) and explain why it has that complexity based on its architecture.

NOTATION RULES:
Choose one consistent mathematical notation and maintain it throughout the entire response.
Define every variable and symbol in prose the first time it appears.
"""

    elif epistemic_mode == "conceptual_explanation":
        epistemic_instructions = """
EPISTEMIC MODE: CONCEPTUAL EXPLANATION

Focus on clear, intuitive explanations of established concepts.
Avoid heavy literature reviews or recent preprints unless directly relevant to the core mechanism.
"""

    depth_enforcer = ""

    if plan.get("depth") in ("medium", "high"):
        depth_enforcer = """
LENGTH & DEPTH ENFORCEMENT:
You are writing a comprehensive research report, NOT a brief summary.
Do not be overly concise. Expand on mechanisms, mathematical proofs, and architectural data flows.
Aim to meet or exceed the target_words for each module by providing rich, technical detail.
"""

    return f"""
You are writing part of a dynamic research report.

USER QUERY:
{state.get('query', '')}

REPORT DEPTH:
{plan.get('depth', 'medium')}

REASONING POLICY:
{plan.get('reasoning_policy', 'evidence_plus_analysis')}

{_evidence_mode_instruction(state.get('evidence_mode', 'literature'))}

{epistemic_instructions}

{depth_enforcer}

{_answer_spec_context(state, state.get('evidence_matrix') or {})}

DOMAIN GUARDRAILS:
{guardrail_text}

WRITE THESE MODULES EXACTLY:
{chr(10).join(module_lines)}

EVIDENCE STATUS:
{chr(10).join(evidence_lines)}

NEED COVERAGE STATUS:
{chr(10).join(coverage_lines)}

AVAILABLE SOURCES:
{paper_block or "(no retrieved sources)"}
{_ledger_context(state)}
{dedup_instruction}

EPISTEMIC SYNTHESIS RULES (CRITICAL):
1. DISTINGUISH COMPARATORS: Separate intervention vs matched comparator. These answer different questions.
2. DECOMPOSE OUTCOMES: Do not use broad outcome labels. Break down into specific measurable markers.
3. SEPARATE PROTOCOLS/SUBGROUPS: Do not pool different intervention protocols as identical. Note differences.
4. DISAGREEMENT ANALYSIS: If reviews disagree, explain WHY using the ledger's disagreements.
5. ROBUSTNESS: Grade conclusions as "Robust", "Probable", "Uncertain", or "Unsupported" based on the ledger.
6. EVIDENCE vs INFERENCE vs CONSENSUS: Separate these clearly. Do not jump from evidence to recommendation.
7. BAN GENERIC ADVICE: Do not give lifestyle/general advice unless explicitly asked. Synthesize evidence.
8. QUANTITATIVE ANCHORING: Ban vague adjectives. Anchor every major claim in measurable dimensions.

CITATION RULES:
Use inline citations as [paper_id=N].
Only cite paper_ids that appear in AVAILABLE SOURCES.
Do not invent citations.
Cite a source only if it specifically supports the claim in that sentence.
Do not cite a source just because it was retrieved. One citation per specific claim, not a stack.

Origin/historical/canonical claims must cite the original primary source; do not cite a later interpretive paper for an original claim unless no primary source is available (and then label it as secondary evidence).

If evidence is weak/none, say so explicitly.
If policy allows first-principles reasoning, label it with "Inference:".
If policy allows speculation, label it with "Speculative:".

For independent_analysis, tradeoffs, risk_analysis, use:
Evidence:
Inference:
Recommendation:

If the answer spec marks a topic as a NON-GOAL, do NOT write about it.
If expected equations are listed, use their canonical form and do not simplify or drop terms.
If required components are listed, explicitly include and explain each one.

Never state a confidence that the evidence does not support; weaken claims when evidence is thin or when a required primary source is missing.

FAITHFULNESS RULES:
Every externally verifiable factual claim must be evidence-backed or explicitly labeled as inference.
Do not present unsupported details as sourced facts.
If an important need is unsupported in NEED COVERAGE STATUS, acknowledge that gap explicitly.

EPISTEMIC TRANSPARENCY (Unknown vs Uncertain vs Unsupported):
- UNKNOWN: the evidence set does not contain the data. Write "No source provides X" or "X is unknown" — this is correct behavior, never a failure.
- UNCERTAIN: evidence exists but varies. Give the range and state what it depends on.
- UNSUPPORTED: never present an unsupported number or factual claim as established.
When a quantitative conclusion depends on missing data, abstain explicitly instead of estimating silently. If you must reason from first principles, prefix with "Inference:" or "Estimate:" and list your assumptions. Never silently invent specific figures.

FORMATTING RULES:
Return markdown content for each module.
Do NOT include the module title as a heading. The system will add headings.
Use bullets, short paragraphs, and tables where useful.
Keep each module near its target_words.
Do NOT create a References section.

EXPERT QUALITY RULES:
Explain mechanisms, not labels.

For complexity/latency claims, ALWAYS distinguish training, prefill, and autoregressive decode. Never give one asymptotic number without the phase.

For scaling claims, distinguish theoretical scaling from observed benchmark scaling.

For deployment claims, discuss memory footprint, latency, parallelism, and ecosystem maturity where relevant.

Prefer conditional judgments ("X is preferable when ...") over generic statements.

Every comparative claim must name the mechanism causing the difference.

If a number is not stated in retrieved sources, rely on established domain knowledge but prefix the sentence with "Inference:".

SYNTHESIS MATRIX (Universal):
MECHANISM & CAUSALITY: Never just state "X is better than Y" or "X causes Y". You MUST explain the underlying mechanism, physical constraint, economic incentive, mathematical proof, or biological pathway that drives the outcome.

EPISTEMIC HIERARCHY: Weight claims by evidence tier. Distinguish between foundational axioms, empirical benchmarks, official standards/guidelines, and theoretical models. Explicitly state when a claim relies on a specific benchmark or standard.

BOUNDARY CONDITIONS & FAILURE MODES: Every model, technology, or theory has a breaking point. Explicitly detail the edge cases, contraindications, asymptotic limits, or failure modes where the dominant approach breaks down or underperforms.

QUANTITATIVE ANCHORING: Ban vague adjectives (e.g., "fast", "expensive", "effective", "risky"). Anchor every major claim in measurable dimensions (e.g., asymptotic bounds, effect sizes, confidence intervals, cost categories, latency percentiles). If exact metrics are absent, define the standard metrics the field uses to evaluate this.

ACTIVE DEBATES: Identify where the current consensus ends. Highlight active debates, competing schools of thought, or recent paradigm shifts that challenge older literature.

STRATEGIC INFERENCE: In independent analysis, do not give generic advice. Synthesize the evidence into a high-level strategic conclusion that maps trade-offs to specific constraints (e.g., "Choose X when constraint A is binding; choose Y when constraint B dominates").

{FORMAT_INSTRUCTION}
""".strip()


def _parse_plain_sections(batch_modules: list[dict], text: str) -> dict[str, dict]:
    text = _clean_content(text)

    sections = {}

    parts = re.split(r"^##\s+(.+?)\s*$", text, flags=re.MULTILINE)

    parsed = []

    if len(parts) >= 3:
        for i in range(1, len(parts), 2):
            title = parts[i].strip()
            content = parts[i + 1].strip() if i + 1 < len(parts) else ""

            parsed.append((title, content))

    used = set()

    for title, content in parsed:
        m = _match_module_header(title, batch_modules)

        if m and m["module_id"] not in used and content:
            sections[m["module_id"]] = {
                "module_id": m["module_id"],
                "title": m["title"],
                "content": content,
                "cited_paper_ids": extract_paper_ids(content),
                "evidence_status": "mixed",
                "confidence": "medium",
            }

            used.add(m["module_id"])

    unmatched = [
        (t, c)
        for t, c in parsed
        if not (
            (_match_module_header(t, batch_modules) or {}).get("module_id") in used
            and c
        )
    ]

    for m in batch_modules:
        if m["module_id"] in used or not unmatched:
            continue

        _, content = unmatched.pop(0)

        if content:
            sections[m["module_id"]] = {
                "module_id": m["module_id"],
                "title": m["title"],
                "content": content,
                "cited_paper_ids": extract_paper_ids(content),
                "evidence_status": "mixed",
                "confidence": "medium",
            }

            used.add(m["module_id"])

    if not sections and batch_modules:
        sections[batch_modules[0]["module_id"]] = {
            "module_id": batch_modules[0]["module_id"],
            "title": batch_modules[0]["title"],
            "content": text,
            "cited_paper_ids": extract_paper_ids(text),
            "evidence_status": "mixed",
            "confidence": "medium",
        }

    return sections


def _invoke_section_batch(
    batch_modules: list[dict],
    paper_block: str,
    state: AgentState,
    evidence_map: dict[str, dict],
    guardrails: list[str],
    plan: dict,
    timeout: int,
) -> dict[str, dict]:
    prompt = _section_batch_prompt(
        batch_modules=batch_modules,
        paper_block=paper_block,
        state=state,
        evidence_map=evidence_map,
        guardrails=guardrails,
        plan=plan,
    )

    full_prompt = (
        prompt
        + "\n\nOUTPUT FORMAT:\n"
        + "Return markdown only. Start each module with a level-2 heading "
        + "exactly matching its title, e.g.:\n"
        + "## Direct Answer\n\n(content)\n\n## Research Findings\n\n(content)\n"
        + "Do NOT wrap in JSON. Do NOT use code fences. Do NOT return a "
        + "SectionBatch object."
    )

    messages = [
        SystemMessage(
            content=(
                "You are a modular research report writer. "
                "Return markdown only."
            )
        ),
        HumanMessage(content=full_prompt),
    ]

    try:
        response_mode = state.get("response_mode", "normal")
        if response_mode in ("researched", "graph_research"):
            section_task = "strong"
        else:
            section_task = "default"
        llm = get_llm(temperature=0, task=section_task)

        raw = llm.invoke(messages, config={"timeout": timeout})

        return _parse_plain_sections(batch_modules, raw.content)

    except Exception as e:
        print(
            f"[summarize] section batch generation failed: {type(e).__name__}: {e}"
        )

        return {}


def _stream_invoke_section_batch(
    batch_modules: list[dict],
    paper_block: str,
    state: AgentState,
    evidence_map: dict[str, dict],
    guardrails: list[str],
    plan: dict,
    timeout: int,
    emitter: _OrderedSectionEmitter | None,
    id_map: dict,
    dedupe_seen: set[str] | None = None,
) -> dict[str, dict]:
    """
    Streaming version: uses llm.stream(), splits on ## header boundaries,
    rewrites citations + sanitizes per section, pushes to ordered emitter.

    Returns partial results on stream error (caller retries missing).
    """
    cancel_check = state.get("_cancel_check")

    if dedupe_seen is None:
        dedupe_seen = set()

    prompt = _section_batch_prompt(
        batch_modules=batch_modules,
        paper_block=paper_block,
        state=state,
        evidence_map=evidence_map,
        guardrails=guardrails,
        plan=plan,
    )

    full_prompt = (
        prompt
        + "\n\nOUTPUT FORMAT:\n"
        + "Return markdown only. Start each module with a level-2 heading "
        + "exactly matching its title, e.g.:\n"
        + "## Direct Answer\n\n(content)\n\n## Research Findings\n\n(content)\n"
        + "Do NOT wrap in JSON. Do NOT use code fences. Do NOT return a "
        + "SectionBatch object."
    )

    messages = [
        SystemMessage(
            content=(
                "You are a modular research report writer. "
                "Return markdown only."
            )
        ),
        HumanMessage(content=full_prompt),
    ]

    title_to_module = {}

    for m in batch_modules:
        title_to_module[m["title"].lower()] = m
        title_to_module[m["module_id"].replace("_", " ").lower()] = m

    def _emit_section(title: str, raw_content: str):
        m = _match_module_header(title, batch_modules)

        if not m:
            return None

        mid = m["module_id"]

        cleaned = _clean_content(raw_content)

        cleaned = _dedupe_paragraphs(cleaned, dedupe_seen)

        cited_ids = extract_paper_ids(cleaned)

        display_content = rewrite_inline_citations(cleaned, id_map)
        display_content = _sanitize_preserving_math(display_content)

        if emitter is not None:
            emitter.submit(mid, f"## {m['title']}\n\n{display_content}\n")

        return {
            "module_id": mid,
            "title": m["title"],
            "content": cleaned,
            "cited_paper_ids": cited_ids,
            "evidence_status": evidence_map.get(mid, {}).get(
                "evidence_status",
                "mixed",
            ),
            "confidence": "medium",
        }

    sections: dict[str, dict] = {}

    try:
        response_mode = state.get("response_mode", "normal")
        if response_mode in ("researched", "graph_research"):
            section_task = "strong"
        else:
            section_task = "default"
        llm = get_llm(temperature=0, task=section_task)

        buffer = ""
        current_title = None
        current_content = ""

        for chunk in llm.stream(messages, config={"timeout": timeout}):
            if cancel_check and cancel_check():
                break

            text = chunk.content if hasattr(chunk, "content") else str(chunk)

            buffer += text

            if current_title is None and buffer.startswith("## "):
                line_end = buffer.find("\n")

                if line_end == -1:
                    continue

                current_title = buffer[3:line_end].strip()
                current_content = ""

                buffer = buffer[line_end + 1:]

                continue

            while True:
                match = re.search(r"\n## (.+)", buffer)

                if not match:
                    break

                header_start = match.start()

                if current_title is not None:
                    current_content += buffer[:header_start]

                    sec = _emit_section(current_title, current_content)

                    if sec:
                        sections[sec["module_id"]] = sec

                after_header = buffer[match.end():]

                line_end = after_header.find("\n")

                if line_end == -1:
                    current_title = after_header.strip()
                    current_content = ""
                    buffer = ""

                    break

                current_title = after_header[:line_end].strip()
                current_content = ""
                buffer = after_header[line_end + 1:]

        if current_title is not None:
            current_content += buffer

            sec = _emit_section(current_title, current_content)

            if sec:
                sections[sec["module_id"]] = sec

        elif buffer.strip() and batch_modules:
            m0 = batch_modules[0]

            cleaned = _clean_content(buffer)
            cleaned = _dedupe_paragraphs(cleaned, dedupe_seen)

            cited_ids = extract_paper_ids(cleaned)

            display_content = rewrite_inline_citations(cleaned, id_map)
            display_content = _sanitize_preserving_math(display_content)

            if emitter is not None:
                emitter.submit(
                    m0["module_id"],
                    f"## {m0['title']}\n\n{display_content}\n",
                )

            sections[m0["module_id"]] = {
                "module_id": m0["module_id"],
                "title": m0["title"],
                "content": cleaned,
                "cited_paper_ids": cited_ids,
                "evidence_status": evidence_map.get(m0["module_id"], {}).get(
                    "evidence_status",
                    "mixed",
                ),
                "confidence": "medium",
            }

    except Exception as e:
        print(
            f"[summarize] streaming batch failed, returning partial: {type(e).__name__}: {e}"
        )

    return sections


def _generate_sections_batch(
    batch_modules: list[dict],
    paper_block: str,
    state: AgentState,
    evidence_map: dict[str, dict],
    guardrails: list[str],
    plan: dict,
    timeout: int,
) -> list[dict]:
    if not batch_modules:
        return []

    sections = _invoke_section_batch(
        batch_modules,
        paper_block,
        state,
        evidence_map,
        guardrails,
        plan,
        timeout,
    )

    missing = [
        m
        for m in batch_modules
        if m["module_id"] not in sections
        and m["module_id"] in (
            "direct_answer",
            "executive_summary",
            "research_findings",
        )
    ]

    if missing:
        print(
            f"[summarize] retrying {len(missing)} missing module(s): "
            f"{[m['module_id'] for m in missing]}"
        )

        retry_sections = _invoke_section_batch(
            missing,
            paper_block,
            state,
            evidence_map,
            guardrails,
            plan,
            timeout,
        )

        sections.update(retry_sections)

    for m in batch_modules:
        mid = m["module_id"]

        if mid not in sections:
            sections[mid] = {
                "module_id": mid,
                "title": m["title"],
                "content": "No content could be generated for this section.",
                "cited_paper_ids": [],
                "evidence_status": evidence_map.get(mid, {}).get(
                    "evidence_status",
                    "none",
                ),
                "confidence": "low",
            }

    return [sections[m["module_id"]] for m in batch_modules]


def _generate_sections_batch_streaming(
    batch_modules: list[dict],
    paper_block: str,
    state: AgentState,
    evidence_map: dict[str, dict],
    guardrails: list[str],
    plan: dict,
    timeout: int,
    emitter: _OrderedSectionEmitter | None,
    id_map: dict,
    dedupe_seen: set[str] | None = None,
) -> list[dict]:
    if not batch_modules:
        return []

    cancel_check = state.get("_cancel_check")

    if dedupe_seen is None:
        dedupe_seen = set()

    sections = _stream_invoke_section_batch(
        batch_modules,
        paper_block,
        state,
        evidence_map,
        guardrails,
        plan,
        timeout,
        emitter,
        id_map,
        dedupe_seen,
    )

    missing = [
        m
        for m in batch_modules
        if m["module_id"] not in sections
        and m["module_id"] in (
            "direct_answer",
            "executive_summary",
            "research_findings",
        )
    ]

    if missing and not (cancel_check and cancel_check()):
        print(f"[summarize:stream] retrying {len(missing)} missing module(s)")

        retry = _invoke_section_batch(
            missing,
            paper_block,
            state,
            evidence_map,
            guardrails,
            plan,
            timeout,
        )

        for mid, sec in retry.items():
            cleaned = _clean_content(sec.get("content", ""))
            cleaned = _dedupe_paragraphs(cleaned, dedupe_seen)

            cited_ids = extract_paper_ids(cleaned)

            display_content = rewrite_inline_citations(cleaned, id_map)
            display_content = _sanitize_preserving_math(display_content)

            sec["content"] = cleaned
            sec["cited_paper_ids"] = cited_ids

            if emitter is not None:
                emitter.submit(
                    mid,
                    f"## {sec['title']}\n\n{display_content}\n",
                )

        sections.update(retry)

    for m in batch_modules:
        mid = m["module_id"]

        if mid not in sections:
            content = _deterministic_section_fallback(
                m,
                state.get("ranked_papers", []),
                state.get("summaries", {}) or {},
                _cite_labels(state.get("ranked_papers", [])),
                state,
            )

            placeholder = {
                "module_id": mid,
                "title": m["title"],
                "content": content,
                "cited_paper_ids": extract_paper_ids(content),
                "evidence_status": evidence_map.get(mid, {}).get(
                    "evidence_status",
                    "none",
                ),
                "confidence": "low",
            }

            sections[mid] = placeholder

            if emitter is not None:
                display_content = _sanitize_preserving_math(content)

                emitter.submit(
                    mid,
                    f"## {m['title']}\n\n{display_content}\n",
                )

    return [sections[m["module_id"]] for m in batch_modules]


def _cite_labels(papers: list[dict]) -> dict[str, str]:
    labels = {}

    for i, p in enumerate(papers):
        authors = p.get("authors") or []

        if authors:
            name = authors[0].split()[-1]
            suffix = " et al." if len(authors) > 1 else ""
        else:
            name, suffix = "Unknown", ""

        year = str(p.get("published") or "")[:4]

        if not year.isdigit():
            year = "n.d."

        labels[str(i)] = f"{name}{suffix} {year}"

    return labels


def _rewrite_citations_author_year(text: str, labels: dict[str, str]) -> str:
    """
    Kept for compatibility with older flows.
    Current pipeline uses rewrite_inline_citations().
    """
    def repl(m):
        lab = labels.get(m.group(1))
        return f"[{lab}]" if lab else ""

    text = re.sub(r"\[paper_id=(\d+)\]", repl, text)

    text = re.sub(
        r"\[(\d+)\]",
        lambda m: f"[{labels[m.group(1)]}]" if m.group(1) in labels else m.group(0),
        text,
    )

    return text


def _deterministic_section_fallback(
    m: dict,
    papers: list[dict],
    summaries: dict,
    labels: dict[str, str],
    state: AgentState,
) -> str:
    mid = m["module_id"]

    qu = state.get("query_understanding") or {}

    candidates = list(
        dict.fromkeys(
            (qu.get("methods_techniques") or []) + (qu.get("entities") or [])
        )
    )[:4]

    lines = []

    if mid == "comparative_analysis" and len(candidates) >= 2:
        for c in candidates:
            key = c.lower().split()[0]

            hit = next(
                (
                    (i, p)
                    for i, p in enumerate(papers)
                    if key in p.get("title", "").lower()
                ),
                None,
            )

            if hit:
                i, p = hit

                s = summaries.get(str(i), {})

                lines.append(
                    f"- **{c}** — [{labels.get(str(i), 'Source')}] "
                    f"{(s.get('findings') or p.get('summary', ''))[:260]}"
                )
            else:
                lines.append(
                    f"- **{c}** — No directly retrieved paper; "
                    f"treat claims about it as inference."
                )

        return (
            "Evidence:\n"
            + "\n".join(lines)
            + (
                "\n\nInference: Head-to-head differences should be interpreted cautiously "
                "because direct comparative studies are limited."
            )
        )

    for i, p in enumerate(papers[:4]):
        s = summaries.get(str(i), {})

        lines.append(
            f"- [{labels.get(str(i), 'Source')}] {p.get('title', '')}: "
            f"{(s.get('findings') or '')[:220]}"
        )

    return (
        "Evidence:\n"
        + "\n".join(lines)
        + "\n\nInference: The retrieved evidence for this section is limited; "
        "treat the synthesis as provisional."
    )


def _split_batches(modules: list[dict], depth: str) -> list[list[dict]]:
    if depth == "low" or len(modules) <= 4:
        return [modules]

    core_ids = {
        "direct_answer",
        "executive_summary",
        "background",
        "key_concepts",
        "methodology",
        "research_findings",
    }

    core = [m for m in modules if m["module_id"] in core_ids]
    analysis = [m for m in modules if m["module_id"] not in core_ids]

    if not core:
        return [analysis] if analysis else [modules]

    if not analysis:
        return [core]

    return [core, analysis]


def _generate_all_sections(
    modules: list[dict],
    paper_block: str,
    state: AgentState,
    evidence_map: dict[str, dict],
    guardrails: list[str],
    plan: dict,
    depth: str,
) -> list[dict]:
    batches = _split_batches(modules, depth)

    timeout = (
        settings.REPORT_SECTION_TIMEOUT_DEEP
        if depth == "high"
        else settings.REPORT_SECTION_TIMEOUT_NORMAL
    )

    if len(batches) == 1:
        return _generate_sections_batch(
            batches[0],
            paper_block,
            state,
            evidence_map,
            guardrails,
            plan,
            timeout,
        )

    sections = []

    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = {
            ex.submit(
                _generate_sections_batch,
                batch,
                paper_block,
                state,
                evidence_map,
                guardrails,
                plan,
                timeout,
            ): batch
            for batch in batches
        }

        for future in as_completed(futures):
            try:
                sections.extend(future.result())
            except Exception as e:
                print(
                    f"[summarize] parallel section generation failed: {type(e).__name__}: {e}"
                )

    return sections


def _generate_all_sections_streaming(
    modules: list[dict],
    paper_block: str,
    state: AgentState,
    evidence_map: dict[str, dict],
    guardrails: list[str],
    plan: dict,
    depth: str,
    emitter: _OrderedSectionEmitter | None,
    id_map: dict,
) -> list[dict]:
    batches = _split_batches(modules, depth)

    timeout = (
        settings.REPORT_SECTION_TIMEOUT_DEEP
        if depth == "high"
        else settings.REPORT_SECTION_TIMEOUT_NORMAL
    )

    dedupe_seen: set[str] = set()

    if len(batches) == 1:
        return _generate_sections_batch_streaming(
            batches[0],
            paper_block,
            state,
            evidence_map,
            guardrails,
            plan,
            timeout,
            emitter,
            id_map,
            dedupe_seen,
        )

    sections: list[dict] = []

    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = {
            ex.submit(
                _generate_sections_batch_streaming,
                batch,
                paper_block,
                state,
                evidence_map,
                guardrails,
                plan,
                timeout,
                emitter,
                id_map,
                dedupe_seen,
            ): batch
            for batch in batches
        }

        for future in as_completed(futures):
            try:
                sections.extend(future.result())
            except Exception as e:
                print(
                    f"[summarize:stream] parallel generation failed: {type(e).__name__}: {e}"
                )

    if emitter is not None:
        emitter.flush_remaining()

    return sections


def _generate_normal_fast_sections(
    papers: list[dict],
    summaries: dict[str, dict],
    state: AgentState,
    plan: dict,
    evidence_map: dict[str, dict],
) -> list[dict]:
    if not papers:
        content = (
            "**Direct answer:** I could not find sufficiently relevant evidence "
            "in the current retrieval set.\n\n"
            "**Evidence:** No usable sources were available.\n\n"
            "**Limitations:** This answer should be treated as low confidence."
        )

        return [
            {
                "module_id": "direct_answer",
                "title": "Direct Answer",
                "content": content,
                "cited_paper_ids": [],
                "evidence_status": "none",
                "confidence": "low",
            }
        ]

    paper_block = _build_paper_block(
        papers,
        summaries,
        max_abstract=350,
        max_papers=3,
    )

    query = state.get("query", "")

    q = query.lower()

    comparison_hint = ""

    if any(
        word in q
        for word in (
            "compare",
            "comparison",
            "versus",
            "vs",
            "difference between",
        )
    ):
        comparison_hint = (
            "Include one compact markdown comparison table if the sources support it. "
            "Keep the table small and factual."
        )

    prompt = f"""
USER QUERY:
{query}

AVAILABLE SOURCES:
{paper_block or "(no retrieved sources)"}

Write ONE concise evidence-backed answer.

Length:
450 to 650 words.

Use these bold labels exactly:
**Direct answer:**
**Evidence:**
**Limitations:**

{comparison_hint}

Rules:
Use only the available sources.
Cite sources using [paper_id=N].
Do not invent citations.
Do not invent metrics.
Do not write a References section.
Do not use markdown headings.
Keep the answer accurate, concise, and high-quality.
""".strip()

    try:
        llm = get_llm(temperature=0, task="default")

        raw = llm.invoke(
            [
                SystemMessage(
                    content=(
                        "You are a concise, evidence-grounded research assistant. "
                        "Return markdown only."
                    )
                ),
                HumanMessage(content=prompt),
            ],
            config={"timeout": settings.REPORT_SECTION_TIMEOUT_NORMAL},
        )

        content = _clean_content(
            raw.content if hasattr(raw, "content") else str(raw)
        )

    except Exception as e:
        print(f"[summarize:normal] fast answer failed: {type(e).__name__}: {e}")

        first = papers[0]

        abstract = (first.get("summary") or first.get("text") or "")[:400]

        content = (
            f"**Direct answer:** The available evidence is limited, but the top retrieved source is: "
            f"{first.get('title', 'Untitled')}.\n\n"
            f"**Evidence:** [paper_id=0] {abstract}\n\n"
            f"**Limitations:** Only limited evidence could be retrieved quickly."
        )

    cited_ids = extract_paper_ids(content)

    return [
        {
            "module_id": "direct_answer",
            "title": "Direct Answer",
            "content": content,
            "cited_paper_ids": cited_ids,
            "evidence_status": evidence_map.get("direct_answer", {}).get(
                "evidence_status",
                "mixed",
            ),
            "confidence": "medium",
        }
    ]


def _collect_cited_paper_ids(sections: list[dict], papers: list[dict]) -> list[str]:
    cited = set()

    for s in sections:
        content = s.get("content", "")

        for pid in extract_paper_ids(content):
            cited.add(str(pid))

        for pid in s.get("cited_paper_ids", []):
            cited.add(str(pid))

    valid = []

    for pid in cited:
        if pid.isdigit() and 0 <= int(pid) < len(papers):
            valid.append(pid)

    return sorted(valid, key=lambda x: int(x))


def _select_default_cited_ids(
    papers: list[dict],
    summaries: dict,
    plan: dict,
) -> list[str]:
    direct_ids = [
        sid
        for sid, s in summaries.items()
        if s.get("evidence_type") == "direct"
    ]

    supporting_ids = [
        sid
        for sid, s in summaries.items()
        if s.get("evidence_type") == "supporting"
    ]

    ids = direct_ids[:3] + supporting_ids[:2]

    if not ids:
        ids = [str(i) for i, _ in enumerate(papers[:3])]

    return ids


def _select_references(
    references: list[dict],
    cited_ref_ids: set[int],
    plan: dict,
    papers: list[dict],
    summaries: dict,
    target_k: int | None = None,
) -> list[dict]:
    policy = plan.get("reference_policy", "standard")
    if policy == "none":
        return []


    if target_k and target_k > 0:
        max_refs = target_k
    else:
        max_refs = {
            "minimal": 4,
            "standard": 8,
            "research": 15,
            "documentation": 8,
        }.get(policy, 8)


    selected = []
    seen = set()


    for r in references:
        rid = r.get("id")
        if rid in cited_ref_ids and rid not in seen:
            selected.append(r)
            seen.add(rid)


    if len(selected) < max_refs:
        for r in references:
            if len(selected) >= max_refs:
                break
            rid = r.get("id")
            if rid in seen:
                continue
            selected.append(r)
            seen.add(rid)


    return selected[:max_refs]


def _compute_dynamic_confidence(
    state: AgentState,
    papers: list[dict],
    summaries: dict,
    sections: list[dict],
    evidence_map: dict[str, dict],
    plan: dict,
) -> dict:
    total = len(papers)

    if total == 0:
        return {
            "evidence_quality": "low",
            "answer_confidence": "low",
            "prediction_confidence": None,
            "recommendation_confidence": None,
            "data_completeness": "low",
            "uncertainty": "high",
            "explanation": "No retrieved evidence was available.",
        }

    counts = _count_evidence_types(summaries)

    direct = counts["direct"]
    supporting = counts["supporting"]

    points = 0.0
    reasons = []

    points += min(direct, 3) * 2.0
    points += min(supporting, 4) * 0.75

    reasons.append(
        f"{direct} direct and {supporting} supporting papers"
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

    if avg_rel >= 0.65:
        points += 2.0
    elif avg_rel >= 0.55:
        points += 1.5
    elif avg_rel >= 0.45:
        points += 1.0
    elif avg_rel >= 0.35:
        points += 0.5

    reasons.append(f"average relevance {avg_rel:.2f}")

    max_cite = max((p.get("citation_count") or 0) for p in papers) if papers else 0

    if max_cite >= 1000:
        points += 1.5
    elif max_cite >= 200:
        points += 1.0
    elif max_cite >= 50:
        points += 0.5

    if total >= 6:
        points += 0.5
    elif total >= 3:
        points += 0.25

    if state.get("low_confidence_results"):
        points -= 2.5
        reasons.append("low semantic relevance in retrieved set")

    abstention_hits = sum(
        1
        for s in sections
        if any(
            m in (s.get("content") or "").lower()
            for m in (
                "unknown", "no source provides", "not available",
                "insufficient evidence", "cannot be quantified",
                "inference:", "estimate:",
            )
        )
    )
    if abstention_hits >= 2 and state.get("low_confidence_results"):
        points += 0.75
        reasons.append("honest abstention on evidence gaps")

    ledger = state.get("reasoning_ledger")
    if ledger:
        n_unsupported = len(ledger.get("unsupported_variables") or [])
        if n_unsupported >= 2:
            points -= 1.5
            reasons.append(f"{n_unsupported} required variables unsupported by sources")

    if direct == 0:
        points -= 1.0

    if points >= 5.5:
        evidence_quality = "high"
        answer_confidence = "high"
    elif points >= 3.0:
        evidence_quality = "medium"
        answer_confidence = "medium"
    else:
        evidence_quality = "low"
        answer_confidence = "low"

    if evidence_quality == "high" and direct == 0:
        evidence_quality = "medium"
        answer_confidence = "medium"

    weak_or_none = 0
    considered = 0

    for mid, entry in evidence_map.items():
        if mid in (
            "references",
            "confidence_uncertainty",
            "background",
            "key_concepts",
        ):
            continue

        considered += 1

        if entry.get("evidence_status") in ("weak", "none"):
            weak_or_none += 1

    if considered == 0:
        data_completeness = "medium"
    elif weak_or_none == 0:
        data_completeness = "high"
    elif weak_or_none <= max(1, considered // 3):
        data_completeness = "medium"
    else:
        data_completeness = "low"

    uncertainty = {
        "high": "low",
        "medium": "moderate",
        "low": "high",
    }.get(evidence_quality, "moderate")

    explanation = "Evidence: " + "; ".join(reasons) + "."

    if ledger and len(ledger.get("unsupported_variables") or []) >= 2:
        if data_completeness == "high":
            data_completeness = "medium"
        if uncertainty == "low":
            uncertainty = "moderate"

    if state.get("low_confidence_results"):
        evidence_quality = "low"
        answer_confidence = "low"
        if data_completeness == "high":
            data_completeness = "medium"
        if uncertainty == "low":
            uncertainty = "moderate"
    return {
        "evidence_quality": evidence_quality,
        "answer_confidence": answer_confidence,
        "prediction_confidence": None,
        "recommendation_confidence": None,
        "data_completeness": data_completeness,
        "uncertainty": uncertainty,
        "explanation": explanation,
    }


def _merge_sections(sections: list[dict], plan: dict) -> str:
    order = {
        m["module_id"]: m.get(
            "order",
            MODULE_LIBRARY.get(m["module_id"], {}).get("order", 9999),
        )
        for m in plan.get("modules", [])
    }

    sections = sorted(
        sections,
        key=lambda s: order.get(s.get("module_id"), 9999),
    )

    parts = []

    for s in sections:
        content = _clean_content(s.get("content", ""))

        if not content:
            continue

        title = s.get("title") or MODULE_LIBRARY.get(
            s.get("module_id"),
            {},
        ).get("title", "Section")

        content = _strip_headers(content)

        parts.append(f"## {title}\n\n{content}\n")

    return "\n".join(parts).strip()


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text or ""))


def _normalize_block_for_dedupe(block: str) -> str:
    block = re.sub(r"\s+", " ", block or "").strip().lower()

    block = re.sub(r"\[paper_id=\d+\]", "", block)
    block = re.sub(r"\[\d+\]", "", block)

    return block


def _is_protected_block(block: str) -> bool:
    stripped = block.strip()

    if not stripped:
        return True

    if stripped.startswith("#"):
        return True

    if "$$" in stripped:
        return True

    if re.search(r"\$[^$\n]+?\$", stripped):
        return True

    if len(stripped) < 80:
        return True

    return False



def _ledger_context(state: AgentState) -> str:
    ledger = state.get("reasoning_ledger")
    if not ledger:
        return ""
    lines = ["REASONING LEDGER (verified, sourced facts — use ONLY these numbers):"]

    extracted = ledger.get("extracted_variables") or []
    if extracted:
        lines.append("VERIFIED FIGURES (each tied to a real source):")
        for v in extracted[:15]:
            if isinstance(v, dict):
                lines.append(
                    f"- {v.get('name', 'figure')}: {v.get('value', '')} {v.get('unit', '')} "
                    f"[paper_id={v.get('source_paper_id', 0)}] "
                    f"(year {v.get('year', '?')}, confidence {v.get('confidence', 'medium')})"
                )

    unsupported = ledger.get("unsupported_variables") or []
    if unsupported:
        lines.append("UNSUPPORTED VARIABLES (NO source provides these — DO NOT invent values; state them as unknown or give the formula/inputs needed):")
        for u in unsupported[:10]:
            lines.append(f"- {u}")

    scenarios = ledger.get("scenario_matrix") or []
    if scenarios:
        lines.append("SCENARIO MATRIX (interpret these rows; do not recalculate):")
        for s in scenarios[:8]:
            if isinstance(s, dict):
                lines.append(
                    f"- {s.get('scenario_name', 'scenario')}: {s.get('outcome', '')} "
                    f"(leading option: {s.get('winning_option', 'n/a')})"
                )

    contradictions = ledger.get("contradictions") or []
    if contradictions:
        lines.append("DETECTED CONTRADICTIONS (present both sides; do not force false consensus):")
        for c in contradictions[:6]:
            if isinstance(c, dict):
                lines.append(
                    f"- {c.get('topic', '')}: {c.get('position_a', '')} "
                    f"[paper_id={c.get('source_a_paper_id', 0)}] vs {c.get('position_b', '')} "
                    f"[paper_id={c.get('source_b_paper_id', 0)}]. Resolution: {c.get('resolution', '')}"
                )

    assumptions = ledger.get("key_assumptions") or []
    if assumptions:
        lines.append("KEY ASSUMPTIONS (state these explicitly before any quantitative conclusion):")
        for a in assumptions[:8]:
            lines.append(f"- {a}")

    return "\n".join(lines)




def _dedupe_paragraphs(
    text: str,
    seen_global: set[str] | None = None,
) -> str:
    """
    Conservative deterministic paragraph deduplication.

    Rules:
    - only remove long duplicated paragraphs/blocks
    - do NOT delete short legitimate repeated phrases
    - do NOT delete equations
    - do NOT delete headings
    - do NOT delete citations by themselves
    - only remove exact normalized duplicates where normalized length > 120
    """
    if not text:
        return ""

    paragraphs = re.split(r"\n{2,}", text)

    kept = []

    seen = seen_global if seen_global is not None else set()

    for para in paragraphs:
        para = para.strip()

        if not para:
            continue

        if _is_protected_block(para):
            kept.append(para)
            continue

        normalized = _normalize_block_for_dedupe(para)

        if len(normalized) <= 120:
            kept.append(para)
            continue

        with _DEDUPE_LOCK:
            if normalized in seen:
                continue

            seen.add(normalized)

        kept.append(para)

    return "\n\n".join(kept)


def _dedupe_sections(sections: list[dict]) -> list[dict]:
    seen: set[str] = set()

    for section in sections:
        section["content"] = _dedupe_paragraphs(
            section.get("content", ""),
            seen,
        )

    return sections


def _expand_shallow_modules(
    sections: list[dict],
    state: AgentState,
    plan: dict,
    papers: list[dict],
    summaries: dict[str, dict],
) -> list[dict]:
    if state.get("response_mode") == "normal":
        return sections

    target_words = int(plan.get("target_words") or 0)

    if target_words <= 0:
        return sections

    current_words = _word_count(_merge_sections(sections, plan))

    if current_words >= int(target_words * 0.60):
        return sections

    expand_ids = []

    for s in sections:
        if s.get("module_id") in (
            "direct_answer",
            "derivation",
            "research_findings",
            "comparative_analysis",
        ):
            if _word_count(s.get("content", "")) < 180:
                expand_ids.append(s.get("module_id"))

    if not expand_ids:
        return sections

    paper_block = _build_paper_block(
        papers,
        summaries,
        max_abstract=900,
        max_papers=min(10, max(5, len(papers))),
    )

    llm = get_llm(temperature=0, task="strong")

    for s in sections:
        if s.get("module_id") not in expand_ids:
            continue

        prompt = f"""
USER QUERY:
{state.get('query', '')}

MODULE TITLE:
{s.get('title', '')}

CURRENT CONTENT:
{s.get('content', '')}

AVAILABLE SOURCES:
{paper_block}

Task:
Expand this module with deeper mechanism-level explanation while preserving factual faithfulness.
Add 120-260 words, keep citations claim-specific as [paper_id=N], and do not repeat sentences.
Return only the revised module content (no heading).
""".strip()

        try:
            raw = llm.invoke(
                [
                    SystemMessage(
                        content=(
                            "You revise one research section for depth and faithfulness."
                        )
                    ),
                    HumanMessage(content=prompt),
                ],
                config={"timeout": settings.REPORT_SECTION_TIMEOUT_NORMAL},
            )

            new_content = _clean_content(
                raw.content if hasattr(raw, "content") else str(raw)
            )

            if _word_count(new_content) > _word_count(s.get("content", "")):
                s["content"] = new_content
                s["cited_paper_ids"] = extract_paper_ids(new_content)

        except Exception as e:
            print(
                f"[summarize] depth expansion failed for {s.get('module_id')}: {type(e).__name__}: {e}"
            )

    return sections


def _generate_premium_normal_sections(
    papers: list[dict],
    summaries: dict[str, dict],
    state: AgentState,
    plan: dict,
    evidence_map: dict[str, dict],
) -> list[dict]:
    if not papers:
        content = (
            "**Direct answer:** I could not find sufficiently relevant evidence "
            "in the current retrieval set.\n\n"
            "**Evidence:** No usable sources were available.\n\n"
            "**Independent analysis:** The answer should be treated as low confidence.\n\n"
            "**Limitations:** This response is limited by lack of retrieved evidence."
        )

        return [
            {
                "module_id": "direct_answer",
                "title": "Direct Answer",
                "content": content,
                "cited_paper_ids": [],
                "evidence_status": "none",
                "confidence": "low",
            }
        ]

    paper_block = _build_paper_block(
        papers,
        summaries,
        max_abstract=450,
        max_papers=4,
    )

    query = state.get("query", "")

    q = query.lower()

    comparison_hint = ""

    if any(
        word in q
        for word in (
            "compare",
            "comparison",
            "versus",
            "vs",
            "difference between",
        )
    ):
        comparison_hint = (
            "Include one compact markdown comparison table if the sources support it. "
            "Keep the table factual and concise."
        )

    prompt = f"""
USER QUERY:
{query}

AVAILABLE SOURCES:
{paper_block or "(no retrieved sources)"}

{_answer_spec_context(state, state.get('evidence_matrix') or {})}

You are a premium research analyst.
Write a concise, high-quality, evidence-backed answer.

Length:
650 to 900 words.

Use these bold labels exactly:
**Direct answer:**
**Evidence:**
**Independent analysis:**
**Limitations:**

{comparison_hint}

Rules:
Answer the exact question. Do not add unrelated applications, surveys, or background unless required by the answer spec.
If the question asks about an original system, theory, algorithm, equation, or architecture, describe the original/canonical version first.
Never invent specific numbers. If quantifying without sources, prefix with "Inference:" or "Estimate:" and state assumptions.
Use only the available sources.
Cite sources using [paper_id=N].
Cite a source only when it directly supports the exact claim; do not cite a source merely because it was retrieved.

Origin/historical claims: cite the primary source when available; otherwise state the claim relies on secondary evidence.

For equations and derivations, use canonical notation, define every symbol, and do not drop scaling terms.
If required components are listed, explicitly include and explain each one.

Do not invent citations.
Do not invent metrics.
Do not overstate certainty.
If critical evidence is missing, reduce certainty and state the gap explicitly.

Clearly separate evidence from inference.
Keep the answer premium, sharp, and useful.

Do not write a References section.
Do not use markdown headings.
""".strip()

    try:
        llm = get_llm(temperature=0, task="default")

        raw = llm.invoke(
            [
                SystemMessage(
                    content=(
                        "You are a premium, evidence-grounded research analyst. "
                        "Return markdown only."
                    )
                ),
                HumanMessage(content=prompt),
            ],
            config={"timeout": settings.REPORT_SECTION_TIMEOUT_NORMAL},
        )

        content = _clean_content(
            raw.content if hasattr(raw, "content") else str(raw)
        )

    except Exception as e:
        print(
            f"[summarize:premium-normal] fast answer failed: {type(e).__name__}: {e}"
        )

        first = papers[0]

        abstract = (first.get("summary") or first.get("text") or "")[:500]

        content = (
            f"**Direct answer:** The available evidence is limited, but the top retrieved source is: "
            f"{first.get('title', 'Untitled')}.\n\n"
            f"**Evidence:** [paper_id=0] {abstract}\n\n"
            f"**Independent analysis:** The answer should be treated as provisional.\n\n"
            f"**Limitations:** Only limited evidence could be retrieved quickly."
        )

    if not content.strip():
        first = papers[0]

        content = (
            f"**Direct answer:** The top retrieved evidence is: {first.get('title', 'Untitled')}.\n\n"
            f"**Evidence:** [paper_id=0] {(first.get('summary') or '')[:400]}\n\n"
            f"**Independent analysis:** The answer should be treated as provisional.\n\n"
            f"**Limitations:** Only limited evidence could be retrieved quickly."
        )

    cited_ids = extract_paper_ids(content)

    return [
        {
            "module_id": "direct_answer",
            "title": "Direct Answer",
            "content": content,
            "cited_paper_ids": cited_ids,
            "evidence_status": evidence_map.get("direct_answer", {}).get(
                "evidence_status",
                "mixed",
            ),
            "confidence": "medium",
        }
    ]


def summarize_node(state: AgentState) -> AgentState:
    papers = state.get("ranked_papers", [])

    plan = state.get("report_plan") or default_report_plan(state)

    depth = plan.get("depth", "low")

    generative_modules = [
        m
        for m in plan.get("modules", [])
        if m.get("module_id") not in ("references", "confidence_uncertainty")
    ]

    if not generative_modules:
        generative_modules = [
            {
                "module_id": "direct_answer",
                "title": "Direct Answer",
                "order": 100,
                "purpose": "Give the explicit answer.",
                "evidence_policy": "evidence_preferred",
                "requires_citations": True,
                "target_words": 200,
            }
        ]

    summaries = _fast_summaries(papers, state)

    summaries = _reclassify_evidence_types(papers, summaries, state)

    evidence_map = _build_module_evidence_map(plan, papers, summaries, state)

    answer_spec = state.get("answer_spec") or {}

    evidence_matrix = _build_evidence_matrix(
        state,
        papers,
        summaries,
        answer_spec,
    )

    state["evidence_matrix"] = evidence_matrix

    paper_block = ""

    guardrails = plan.get("domain_guardrails", [])

    references = build_references(papers)

    if state.get("evidence_mode") == "uploaded":
        references = [
            r
            for r in references
            if r.get("source") == "user_upload"
        ]

    id_map = paper_id_to_ref_id_map(papers, references)

    request_id = state.get("_request_id", "")

    streaming_enabled = bool(request_id and state.get("_streaming_enabled"))

    if state.get("response_mode", "normal") == "normal":
        sections = _generate_premium_normal_sections(
            papers=papers,
            summaries=summaries,
            state=state,
            plan=plan,
            evidence_map=evidence_map,
        )

    else:
        depth_to_max = {
            "low": 6,
            "medium": 8,
            "high": 10,
        }

        max_papers = min(len(papers), depth_to_max.get(depth, 8))

        max_abstract = 750

        paper_block = _build_paper_block(
            papers,
            summaries,
            max_abstract=max_abstract,
            max_papers=max_papers,
        )

        if streaming_enabled:
            ordered_ids = [m["module_id"] for m in generative_modules]

            emitter = _OrderedSectionEmitter(
                ordered_module_ids=ordered_ids,
                request_id=request_id,
                cancel_check=state.get("_cancel_check"),
            )

            sections = _generate_all_sections_streaming(
                generative_modules,
                paper_block,
                state,
                evidence_map,
                guardrails,
                plan,
                depth,
                emitter,
                id_map,
            )

        else:
            sections = _generate_all_sections(
                generative_modules,
                paper_block,
                state,
                evidence_map,
                guardrails,
                plan,
                depth,
            )

        sections = _expand_shallow_modules(
            sections,
            state,
            plan,
            papers,
            summaries,
        )

    sections = _dedupe_sections(sections)

    cited_paper_ids = _collect_cited_paper_ids(sections, papers)

    if not cited_paper_ids:
        cited_paper_ids = _select_default_cited_ids(papers, summaries, plan)

    for s in sections:
        s["content"] = _clean_content(s.get("content", ""))

    cited_ref_ids = set()

    for pid in cited_paper_ids:
        if pid in id_map:
            cited_ref_ids.add(id_map[pid])

    selected_refs = _select_references(
        references,
        cited_ref_ids,
        plan,
        papers,
        summaries,
        target_k=state.get("target_paper_k"),
    )

    dynamic_confidence = _compute_dynamic_confidence(
        state,
        papers,
        summaries,
        sections,
        evidence_map,
        plan,
    )

    answer_text = _merge_sections(sections, plan)

    cite_markers: list[str] = []

    def _stash_cite_marker(m):
        cite_markers.append(m.group(0))
        return f"@@PAPER_CITE_{len(cite_markers) - 1}@@"

    answer_text = re.sub(
        r"[\[【]\s*paper[\s_]?id\s*[=＝]\s*\d+\s*[\]】]",
        _stash_cite_marker,
        answer_text,
        flags=re.IGNORECASE,
    )
    answer_text = _sanitize_preserving_math(answer_text)

    for i, marker in enumerate(cite_markers):
        answer_text = answer_text.replace(f"@@PAPER_CITE_{i}@@", marker)

    from app.agents.report_modules import get_disclaimer


    disclaimer = get_disclaimer()
    if disclaimer and disclaimer not in answer_text:
        answer_text = answer_text.rstrip() + "\n\n---\n\n*" + disclaimer + "*"

    domain_caveat = None

    if state.get("low_confidence_results"):
        low_conf_note = (
            "Few strongly relevant papers were found, so the relevance threshold was relaxed. "
            "Treat this answer as a starting point rather than a comprehensive review."
        )

        domain_caveat = (
            f"{domain_caveat} {low_conf_note}"
            if domain_caveat
            else low_conf_note
        )

    return {
        "summaries": summaries,
        "final_answer": answer_text.strip(),
        "coverage_gaps": [],        
        "domain_caveat": None,      
        "references": selected_refs,
        "section_outputs": sections,
        "module_evidence_map": evidence_map,
        "dynamic_confidence": dynamic_confidence,
        "cited_paper_ids": cited_paper_ids,
        "report_plan": plan,
        "evidence_matrix": evidence_matrix,
    }