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
    CitationNumberer,
    build_references,
    paper_id_to_ref_id_map,
    rewrite_inline_citations,
    format_reference_block,
    extract_paper_ids,
    split_multi_cites,
)
from app.agents.conversation_context import conversation_block, format_override
from app.agents.report_modules import default_report_plan, MODULE_LIBRARY, _is_technical_derivation
from app.utils.text_sanitizer import sanitize_for_web
from app.services.sse import bridge_push
from app.config import settings
from app.services.citation_grounding import (
    ABSTAIN_TEXT,
    ground_text,
    verify_support,
    MARKER_RE,
    extract_quantities,
    rewrite_sentences,
    user_numeric_tokens,
)


llm = get_llm(temperature=0, task="default")



MODULE_TOKENS = {"direct_answer": 450, "executive_summary": 600, "key_concepts": 900,
                 "background": 900, "derivation": 1800, "architecture": 1500,
                 "boundary_conditions": 1200, "research_findings": 1600}


SLIM_FORMAT = """Return only the final markdown for this ONE section. No heading, no <think>.
Math: inline $x$; display math as $$ on its own lines with blank lines around; define each symbol once;
use the canonical formula (e.g. softmax(QK^T/sqrt(d_k))V), never drop sqrt or normalisation.
Cite as [paper_id=N], one id per bracket, only ids listed under ALLOWED SOURCES, only for what that
excerpt states. Never write a number not in a cited excerpt. If sources don't cover something, say so.
Never say "retrieved sources", "ledger" or "the user". No References section."""


_EMPTY_ANSWER_FALLBACK = (
    "I could not find enough directly supporting evidence in the available sources "
    "to answer this reliably. Please provide more context or retry."
)

def _dynamic_paper_cap(papers, depth, hard_max=15):
    strong = sum(1 for p in papers if float(p.get("_relevance_orig") or p.get("final_score") or 0) >= 0.45)
    base = {"low": 6, "medium": 9, "high": 12}.get(depth, 9)
    return max(4, min(hard_max, len(papers), max(base, strong)))


def _block_for_ids(papers, summaries, ids, chars):
    return "\n\n".join(
        f"[paper_id={i}] Title: {papers[i].get('title','')} ({str(papers[i].get('published') or '')[:4]})\n"
        f"Abstract: {((summaries.get(str(i)) or {}).get('findings') or papers[i].get('summary') or '')[:chars]}"
        for i in ids)


def _slim_prompt(m, block, ids, state, plan, guardrails, titles):
    others = ", ".join(t for t in titles if t != m["title"])
    derive = ("Derive step by step: one transformation per display equation, say why each step is valid, "
              "define every symbol and dimension on first use.\n"
              if m["module_id"] == "derivation" else "")
    return f"""{_mode_positioning(state.get('response_mode','normal'))}
USER QUERY: {state.get('query','')}
{conversation_block(state)}
{format_override(state)}
{_evidence_mode_instruction(state.get('evidence_mode','literature'))}
{_answer_spec_context(state, {})}
DOMAIN GUARDRAILS: {'; '.join(guardrails) or 'none'}
SECTION: {m['title']}
GOAL: {m['purpose']}
{derive}Length: about {m.get('target_words', 250)} words. Do not repeat these other sections: {others or 'none'}.
ALLOWED SOURCES: {', '.join(map(str, ids)) or 'none'}
{block}
{_ledger_context(state)}
{GROUNDING_RULES}
{SLIM_FORMAT}"""


def _generate_sections_per_module(modules, papers, summaries, state, evidence_map,
                                  guardrails, plan, emitter, depth):
    cancel = state.get("_cancel_check")
    seen_ids = state.setdefault("_seen_paper_ids", set())
    dedupe_seen, sections = set(), []
    titles = [m["title"] for m in modules]
    limit = _request_token_limit()
    n_cap = _dynamic_paper_cap(papers, depth)
    task = "strong" if state.get("response_mode") in ("researched", "graph_research") else "default"
    timeout = settings.REPORT_SECTION_TIMEOUT_DEEP

    for m in modules:
        if cancel and cancel(): break
        mid = m["module_id"]
        max_out = min(MODULE_TOKENS.get(mid, 1200), int(limit * 0.30))
        want = 10 if mid == "research_findings" else 6
        ids = [int(x) for x in evidence_map.get(mid, {}).get("paper_ids", []) if str(x).isdigit() and int(x) < n_cap]
        ids += [i for i in range(n_cap) if i not in ids]
        ids = list(dict.fromkeys(ids))[:want]

        fixed = _estimate_tokens(_slim_prompt(m, "", ids, state, plan, guardrails, titles))
        budget_chars = max(0, int(limit * 0.70) - max_out - fixed) * 4
        while len(ids) > 2 and budget_chars // len(ids) < 300:
            ids.pop()
        chars = max(300, min(1100, budget_chars // max(1, len(ids))))
        block = _block_for_ids(papers, summaries, ids, chars)
        seen_ids.update(str(i) for i in ids)
        prompt = _slim_prompt(m, block, ids, state, plan, guardrails, titles)

        content = ""
        for _ in range(2):
            try:
                raw = get_llm(temperature=0, task=task).invoke(
                    [SystemMessage(content="You write one section of a research report. Markdown only."),
                     HumanMessage(content=prompt)],
                    max_tokens=max_out, config={"timeout": timeout})
                content = _clean_content(raw.content)
                content = _strip_leading_title(content, m["title"])
                if len(content.split()) >= 25: break
            except Exception as e:
                print(f"[summarize] module {mid} failed: {type(e).__name__}: {e}")
        if len(content.split()) < 25:
            content = _deterministic_section_fallback(m, papers, summaries, {}, state)
            content = _strip_leading_title(content, m["title"])

        content = _dedupe_paragraphs(_rewrite_author_year_markers(content, papers), dedupe_seen)
        sections.append({"module_id": mid, "title": m["title"], "content": content,
                         "cited_paper_ids": extract_paper_ids(content),
                         "evidence_status": evidence_map.get(mid, {}).get("evidence_status", "mixed"),
                         "confidence": "medium"})
        if emitter:
            emitter.submit(mid, f"## {m['title']}\n\n{_sanitize_preserving_math(content)}\n")
    if emitter: emitter.flush_remaining()
    return sections


FORMAT_INSTRUCTION = """
OUTPUT DISCIPLINE:
Never output <think>, thinking, chain-of-thought, internal analysis, planning, drafts, or reasoning.
Return only final user-facing content.

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
1. NUMERICAL GROUNDING: Never invent specific numbers, dollar amounts, percentages, or dates. Use ONLY figures present in the REASONING LEDGER. If a required figure is listed under UNSUPPORTED VARIABLES, do not guess it — state that it is unknown, or describe the formula/inputs needed to derive it. If you must provide an estimate, explicitly state your assumptions in the sentence rather than using labels.
2. CITATION LAUNDERING BAN: Never cite a paper by analogy (e.g. "this health-systems finding applies to energy"). If a retrieved source does not directly study the query's domain, do not cite it for domain claims.
3. INTERNAL CONSISTENCY: If you define strategies, scenarios, or categories, use the exact same names throughout. Do not rename them mid-report.
4. SCENARIO DISCIPLINE: If a scenario matrix is provided, answer resilience/robustness questions by referencing specific scenario rows, not by asserting a single option is "best" unconditionally.

Cite a source ONLY if it specifically supports the exact claim in that sentence.
Do not cite a paper just because it was retrieved.

CITATION COMPLETENESS:
If you use ANY fact, number, mechanism, finding, definition, example, comparison point,
historical claim, equation, dataset, benchmark, or inference from a retrieved paper,
you MUST cite that paper in the sentence where it is used.

Using a source silently is forbidden.
If you cannot cite a paper for a specific claim, do not use that paper's content.

Recent ≠ relevant. Do not introduce a paper's topic (e.g. a new attention variant,
a compression method, an unrelated domain application) unless the user's question
is actually about that topic.

INTEGRITY RULE:
Do not state that a review, search, evaluation, or synthesis was conducted unless the user explicitly asks about methodology and you are describing the cited evidence. If you are explaining a well-established concept using one primary source, say so plainly.
"""

def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _request_token_limit() -> int:
    """Single source of truth for the per-request token ceiling (config.LLM_MAX_PROMPT_TOKENS)."""
    return int(getattr(settings, "LLM_MAX_PROMPT_TOKENS", 8000) or 8000)


def _visible_ids_from_block(block: str) -> set[str]:
    return set(re.findall(r"\[paper_id=(\d+)\]", block or ""))


_NUM_TOKEN_RE = re.compile(r"\d+(?:[.,]\d+)?")


def _number_token_set(text: str) -> set[str]:
    return {n.replace(",", "") for n in _NUM_TOKEN_RE.findall(text or "")}


def _mode_positioning(response_mode: str) -> str:
    return (
        "INTERNAL STYLE RULE: Answer the question directly. "
        "Do not describe the assistant's internal search, retrieval, verification, "
        "revision, citation-checking, or report-generation process. "
        "When methodology is relevant, describe only the cited evidence's methodology, "
        "not the assistant's pipeline. "
        "Never claim systematic-review, PRISMA, protocol, or exhaustive-search rigor."
    )


def _add_missing_numeric_citations(
    sections: list[dict],
    papers: list[dict],
    state: AgentState,
) -> list[dict]:
    """
    Conservative citation repair.

    If a sentence contains quantitative claims and has no citation, but the exact
    numeric tokens appear in one or more shown sources, add the matching paper_ids.
    """
    if not sections or not papers:
        return sections

    visible = (
        state.get("_seen_paper_ids")
        or state.get("_visible_paper_ids")
        or {str(i) for i in range(len(papers))}
    )

    source_tokens: dict[str, set[str]] = {}

    for i, p in enumerate(papers):
        pid = str(i)
        if pid not in visible:
            continue

        blob = (
            f"{p.get('title', '')}. "
            f"{p.get('summary') or p.get('text') or ''}"
        )
        source_tokens[pid] = _number_token_set(blob)

    if not source_tokens:
        return sections

    user_numbers = state.get("_user_numeric_tokens") or set()

    def _cite_sentence(sent: str) -> str:
        if MARKER_RE.search(sent):
            return sent

        if user_numbers and (_number_token_set(sent) & user_numbers):
            return sent

        quants = extract_quantities(sent)
        if not quants:
            return sent

        candidate_sets = []

        for quant in quants:
            qset = set(quant)
            candidates = {
                pid
                for pid, toks in source_tokens.items()
                if qset <= toks
            }

            if not candidates:
                return sent

            candidate_sets.append(candidates)

        common = set.intersection(*candidate_sets)
        if not common:
            return sent

        markers = "".join(
            f"[paper_id={pid}]"
            for pid in sorted(common, key=int)
        )

        return sent.rstrip() + " " + markers

    for sec in sections:
        content = sec.get("content") or ""

        if not content:
            continue

        if ABSTAIN_TEXT in content:
            continue

        new_content = rewrite_sentences(content, _cite_sentence)

        if new_content != content:
            sec["content"] = new_content
            sec["cited_paper_ids"] = extract_paper_ids(new_content)

    return sections


def _enforce_groq_request_budget_raw(prompt: str, max_output_tokens: int) -> str:
    """
    Trims verbose prompt sections when the prompt would exceed the per-request ceiling
    (config.LLM_MAX_PROMPT_TOKENS) to prevent 413 errors.
    """
    target_prompt_tokens = _request_token_limit() - 500 - max_output_tokens
    target_chars = target_prompt_tokens * 4
    
    if len(prompt) <= target_chars:
        return prompt

    prompt = re.sub(
        r"EVIDENCE MATRIX.*?(?=DOMAIN GUARDRAILS|WRITE THESE MODULES|NEED COVERAGE|AVAILABLE SOURCES)",
        "",
        prompt,
        flags=re.DOTALL
    )
    
    if "EPISTEMIC MODE: TEXTBOOK DERIVATION" in prompt:
        prompt = re.sub(
            r"EPISTEMIC MODE: TEXTBOOK DERIVATION.*?(?=DEPTH & MATURITY|EPISTEMIC SYNTHESIS|CITATION RULES|FORMAT INSTRUCTION)",
            "EPISTEMIC MODE: TEXTBOOK DERIVATION\nProvide rigorous step-by-step math. Use $ and $$ correctly. Define all symbols.\n",
            prompt,
            flags=re.DOTALL
        )
        
    prompt = re.sub(
        r"SCENARIO MATRIX.*?(?=AVAILABLE SOURCES|EPISTEMIC SYNTHESIS|NEED COVERAGE|FORMAT INSTRUCTION|\Z)",
        "",
        prompt,
        flags=re.DOTALL
    )
    prompt = re.sub(
        r"DETECTED CONTRADICTIONS.*?(?=AVAILABLE SOURCES|EPISTEMIC SYNTHESIS|NEED COVERAGE|FORMAT INSTRUCTION|\Z)",
        "",
        prompt,
        flags=re.DOTALL
    )
    
    prompt = re.sub(
        r"OTHER SECTIONS IN THIS REPORT.*?(?=EPISTEMIC SYNTHESIS|CITATION RULES|FORMAT INSTRUCTION)",
        "Do not repeat content from other sections.\n",
        prompt,
        flags=re.DOTALL
    )

    if len(prompt) > target_chars:
        prompt = re.sub(
            r"NEED COVERAGE STATUS:\n(.*?)(?=AVAILABLE SOURCES|EPISTEMIC SYNTHESIS|FORMAT INSTRUCTION)",
            lambda m: "NEED COVERAGE STATUS:\n" + "\n".join(m.group(1).split("\n")[:8]) + "\n",
            prompt,
            flags=re.DOTALL
        )

    if len(prompt) > target_chars and "AVAILABLE SOURCES:" in prompt:
        parts = prompt.split("AVAILABLE SOURCES:")
        if len(parts) == 2:
            before = parts[0]
            split_markers = ["\n\nEPISTEMIC SYNTHESIS RULES", "\n\nFORMATTING RULES", "\n\nCITATION RULES", "\n\nEXPERT QUALITY RULES"]
            papers_text = parts[1]
            rest = ""
            for marker in split_markers:
                if marker in parts[1]:
                    p_parts = parts[1].split(marker, 1)
                    papers_text = p_parts[0]
                    rest = marker + p_parts[1]
                    break
            
            allowed_chars = max(800, target_chars - len(before) - len(rest) - 20)
            if len(papers_text) > allowed_chars:
                papers_text = _shrink_paper_text(papers_text, allowed_chars)
            prompt = before + "AVAILABLE SOURCES:" + papers_text + rest

    return prompt


def _cap_findings(summaries: dict[str, dict], cap: int) -> dict[str, dict]:
    return {
        k: {**v, "findings": (v.get("findings") or "")[:cap]}
        for k, v in summaries.items()
    }


_PAPER_START_RE = re.compile(r"(?m)^(?=\[paper_id=\d+\])")
_MIN_CHARS_PER_PAPER = 400


def _shrink_paper_text(text: str, allowed_chars: int) -> str:
    """
    Fit the AVAILABLE SOURCES text into `allowed_chars` WITHOUT cutting the tail off
    mid-paper: every paper keeps a share of the space; if the share would be too small
    to be useful, whole lowest-ranked papers are dropped instead.
    """
    chunks = [c for c in _PAPER_START_RE.split(text) if c.strip()]
    head = ""
    if chunks and not chunks[0].lstrip().startswith("[paper_id="):
        head = chunks.pop(0)
    if not chunks:
        return text[:allowed_chars]

    budget = max(allowed_chars - len(head), _MIN_CHARS_PER_PAPER)
    keep = len(chunks)
    if budget // keep < _MIN_CHARS_PER_PAPER:
        keep = max(2, budget // _MIN_CHARS_PER_PAPER)
    per = budget // keep

    out = []
    for c in chunks[:keep]:
        c = c.strip()
        if len(c) > per:
            c = c[:per].rsplit(" ", 1)[0].rstrip() + " ..."
        out.append(c)
    return "\n" + head + "\n\n".join(out)


def _enforce_groq_request_budget(prompt: str, max_output_tokens: int) -> str:
    """Trim to the request ceiling, then make sure the prompt only allows citing papers it still shows."""
    out = _enforce_groq_request_budget_raw(prompt, max_output_tokens)
    shown = _visible_ids_from_block("\n".join(re.findall(r"(?m)^\[paper_id=\d+\].*$", out)))

    def _filter(m: re.Match) -> str:
        ids = [i for i in m.group(1).split(",") if i.strip() in shown]
        return "allowed_paper_ids=" + (",".join(ids) or "none")

    out = re.sub(r"allowed_paper_ids=([\d,\s]+)", _filter, out)
    print(
        f"[summarize:prompt] est_prompt_tokens={_estimate_tokens(out)} "
        f"max_output={max_output_tokens} limit={_request_token_limit()} "
        f"papers_shown={sorted(shown, key=int)}"
    )
    return out


def _record_seen_ids(state: AgentState, prompt: str) -> None:
    """Remember which papers the model really saw (after trimming) for the grounding pass."""
    seen = state.setdefault("_seen_paper_ids", set())
    seen.update(re.findall(r"(?m)^\[paper_id=(\d+)\]", prompt))


def _fit_paper_block_to_budget(
    papers: list[dict],
    summaries: dict[str, dict],
    prompt_overhead_tokens: int,
    max_output_tokens: int,
    tpm_limit: int = None,
    max_abstract: int = 1000,
    max_papers: int = 8,
    min_papers: int = 4,
) -> str:
    """
    Fits the paper block into the request budget.
    Shrinks each paper's text first and only then drops papers - never below
    `min_papers`, because the model must SEE every paper it is allowed to cite.
    """
    limit = tpm_limit or _request_token_limit()
    budget = max(int(limit * 0.85) - max_output_tokens - prompt_overhead_tokens, 500)

    n_papers = max(1, min(max_papers, len(papers)))
    floor_papers = min(min_papers, n_papers)
    cap = max_abstract

    print(
        f"[summarize:budget] START input_papers={len(papers)} max_papers={n_papers} "
        f"findings_cap={cap} request_limit={limit} budget={budget} "
        f"prompt_overhead={prompt_overhead_tokens} max_output={max_output_tokens}"
    )

    while True:
        block = _build_paper_block(
            papers,
            _cap_findings(summaries, cap),
            max_abstract=cap,
            max_papers=n_papers,
        )
        est = _estimate_tokens(block)
        print(f"[summarize:budget] CHECK n_papers={n_papers} findings_cap={cap} estimated_tokens={est} budget={budget}")

        if est <= budget:
            print(f"[summarize:budget] FIT n_papers={n_papers} findings_cap={cap}")
            return block

        if cap > 300:
            cap = int(cap * 0.75)
        elif n_papers > floor_papers:
            n_papers -= 1
        elif cap > 150:
            cap = 150
        else:
            print(f"[summarize:budget] LAST_RESORT n_papers={n_papers} findings_cap={cap}")
            return block


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
        numberer: "CitationNumberer | None" = None,
    ):
        self.order = ordered_module_ids
        self.request_id = request_id
        self.cancel_check = cancel_check
        self.numberer = numberer
        self._single = len(ordered_module_ids) == 1

        self._ready: dict[str, str] = {}
        self._next = 0
        self._lock = threading.Lock()

    def _prepare(self, content: str) -> str:
        if self._single:
            content = re.sub(r"^\s*##[^\n]*\n+", "", content, count=1)
        if self.numberer is not None:
            content = self.numberer.rewrite(content)
        return content

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

            bridge_push(self.request_id, ("section", mid, self._prepare(content)))

    def flush_remaining(self) -> None:
        with self._lock:
            for mid in self.order[self._next:]:
                if mid in self._ready:
                    content = self._ready.pop(mid)
                    bridge_push(self.request_id, ("section", mid, self._prepare(content)))

            self._next = len(self.order)


_INTERNAL_TAG_NAMES = (
    r"thinking|thought|think|analysis|scratchpad|internal|"
    r"reasoning|reflection|planning|plan|chain-of-thought|chain|cot"
)

_INTERNAL_BLOCK_RE = re.compile(
    rf"<\s*(?P<tag>{_INTERNAL_TAG_NAMES})\b[^>]*>.*?<\s*/\s*(?P=tag)\s*>",
    re.IGNORECASE | re.DOTALL,
)

_UNCLOSED_INTERNAL_BLOCK_RE = re.compile(
    rf"<\s*(?:{_INTERNAL_TAG_NAMES})\b[^>]*>.*",
    re.IGNORECASE | re.DOTALL,
)

def _strip_internal_monologue(text: str) -> str:
    if not text:
        return ""

    previous = None
    while previous != text:
        previous = text
        text = _INTERNAL_BLOCK_RE.sub("", text)

    text = _UNCLOSED_INTERNAL_BLOCK_RE.sub("", text)

    text = re.sub(
        r"^\s*(?:Here'?s a thinking process:|Thinking process:|Let'?s think step by step:?)\s*",
        "",
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    )

    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


_DISCLAIMER_RE = re.compile(
    r"(?im)^[ \t>*_-]*(?:(?:medical|legal|financial)\s+)?disclaimer\b.*\n?"
    r"|^[^\n]*(?:not a substitute for professional (?:medical|legal|financial) advice|consult a qualified (?:healthcare|medical|legal|financial))[^\n]*\n?")

_MATH_DISPLAY_RE = re.compile(r"\$\$(.*?)\$\$", re.DOTALL)
_MATH_INLINE_RE  = re.compile(r"\$([^$\n]+?)\$")
_DEDUPE_LOCK = threading.Lock()


_LATEX_DISPLAY_BRACKET_RE = re.compile(r"\\\[(.+?)\\\]", re.DOTALL)
_LATEX_INLINE_PAREN_RE    = re.compile(r"\\\((.+?)\\\)", re.DOTALL)
_CITE_SOURCE_ARTIFACT_RE = re.compile(
    r"\[\s*(?:paper[\s_]?id\s*[=＝]\s*)?(\d+)\s*(?:[*•,;:]\s*)?source\s*\]",
    re.IGNORECASE,
)
_AUTHOR_YEAR_RE = re.compile(
    r"\[\s*([A-Z][\w'-]+)(?:\s+et\s+al\.?)?\s*[,.]?\s*((?:19|20)\d{2})\s*\]"
)

def _normalize_latex_delimiters(text: str) -> str:
    if not text:
        return ""
    text = re.sub(
        r"\[(paper_id=\d+)\]",
        r"@@CITE_\1@@",
        text,
    )
    text = _LATEX_DISPLAY_BRACKET_RE.sub(
        lambda m: "\n\n$$" + m.group(1).strip() + "$$\n\n", text)
    text = _LATEX_INLINE_PAREN_RE.sub(
        lambda m: "$" + m.group(1).strip() + "$", text)
    text = re.sub(r"@@CITE_(paper_id=\d+)@@", r"[\1]", text)
    return text

def _normalize_citation_artifacts(text: str) -> str:
    """[3*source] / [3, source] / [paper_id=3*source] -> [paper_id=3]."""
    if not text:
        return ""
    return _CITE_SOURCE_ARTIFACT_RE.sub(r"[paper_id=\1]", split_multi_cites(text))

def _rewrite_author_year_markers(text: str, papers: list[dict]) -> str:
    """[Krizhevsky et al. 2012] -> [paper_id=N] via first-author-last-name + year."""
    if not text:
        return ""
    labels = {}
    for i, p in enumerate(papers):
        authors = p.get("authors") or []
        if not authors:
            continue
        labels[(authors[0].split()[-1].lower(), str(p.get("published") or "")[:4])] = i
    def _sub(m):
        pid = labels.get((m.group(1).lower(), m.group(2)))
        return f"[paper_id={pid}]" if pid is not None else ""
    return _AUTHOR_YEAR_RE.sub(_sub, text)

def _section_max_tokens(state: AgentState, plan: dict) -> int:
    if state.get("response_mode", "normal") == "normal":
        return 2048
    base = 4096 if plan.get("depth") == "high" else 3200
    return min(base, int(_request_token_limit() * 0.30))


_CITE_MARKER_RE = re.compile(
    r"[\[【]\s*paper[\s_]?id\s*[=＝]\s*\d+\s*[\]】]",
    re.IGNORECASE,
)

_COMPARE_RE = re.compile(
    r"(?<!\w)(vs\.?|versus|differences?|difference between|differ|compare[sd]?|"
    r"comparison|better than|which is better)(?!\w)",
    re.IGNORECASE,
)


def _repair_numeric_citations(text: str) -> str:
    """
    Fixes LLMs that ignore the [paper_id=N] rule and output standard [1], [2] citations.
    Converts [1] -> [paper_id=0], [1, 2] -> [paper_id=0][paper_id=1].
    """
    def repl(m):
        try:
            nums = [int(n.strip()) - 1 for n in m.group(1).split(",")]
            return "".join(f"[paper_id={n}]" for n in nums if n >= 0)
        except ValueError:
            return m.group(0)
    return re.sub(r"\[(\d+(?:\s*,\s*\d+)*)\]", repl, text)
def _is_comparison_query(q: str) -> bool:
    return bool(_COMPARE_RE.search(q or ""))


PLAIN_LANGUAGE_RULES = """
WRITING STYLE (CRITICAL - overrides any earlier instruction about jargon or labels):
- Write for a smart non-specialist (a final-year student), not for a journal reviewer and not for a child.
- Short sentences. One idea per sentence. Prefer common words.
- When you must use a technical term, add a few plain words the first time (e.g. "beta-1 receptors (the ones mainly in the heart)").
- Say what a finding means in practice, not just what was measured.
- NEVER mention "the retrieved sources", "the provided literature", "the evidence set", "the ledger", or "the user". Say "studies show", "research suggests", or "the evidence is limited".
- Do not use grading labels like Robust / Probable / Unsupported. Use plain words: "strong evidence", "some evidence", "little evidence".
- Use bullets with one idea each. No inline label chains like "Mechanistic risks - ... Evidence - ... Failure mode - ...".
""".strip()


GROUNDING_RULES = """
EVIDENCE RULES (CRITICAL - these override anything above that allows guessing):
You only see each paper's title and a short excerpt. Treat that text as your ONLY evidence for cited claims.
Put [paper_id=N] only on a claim that paper's excerpt actually states. Never cite a paper whose excerpt you were not shown.
If a claim relies on a shown paper, include [paper_id=N] in that same sentence.
Using a source without citing it is a failure.
Never write a number, range, ratio, percentage, duration or sample size unless it appears word for word in a cited excerpt. If the excerpt gives no figure, describe the effect in words and do not invent one.
If the excerpts do not cover a sub-topic, you may add textbook-level background as plain prose with NO citation marker, NO numbers, NO heading, and NO label. Never say "not from retrieved sources".
Numbers that appear in the USER QUERY are the user's own observations. Report them as the user's data. Never cite a paper for them, never say they were retrieved, and compare them with literature only using figures stated in a cited excerpt. Never invent a "typical range".
Reviews and overviews support only what their excerpt says; do not cite them for mechanisms, side effects or subgroups the excerpt does not mention.
""".strip()


def _comparison_rules(scope: str = "The answer") -> str:
    return f"""
COMPARISON QUESTION - {scope} MUST start like this:
1. One sentence verdict in plain words (what is the main difference, which is preferred, and when).
2. A compact markdown table: Feature | A | B with 4-6 rows (e.g. main target, main effect, side effects, who it suits, main caution).
3. Two or three bullets: "Choose A when ...", "Choose B when ...".
Only after that give supporting evidence. Do not bury the difference.
""".strip()


def _ground_sections(sections: list[dict], papers: list[dict], state: AgentState) -> list[dict]:
    if not sections or not papers:
        return sections
    texts_by_id = {
        str(i): f"{p.get('title', '')}. {p.get('summary') or p.get('text') or ''}"
        for i, p in enumerate(papers)
    }
    visible = state.get("_seen_paper_ids") or state.get("_visible_paper_ids") or set(texts_by_id)
    numeric_on = getattr(settings, "GROUNDING_NUMERIC_CHECK_ENABLED", True)
    is_normal = state.get("response_mode", "normal") == "normal"
    drops: list[dict] = []
    bodies = []
    
    marker = "### Established background (not from retrieved sources)"
    
    for sec in sections:
        content = sec.get("content") or ""
        head, sep, tail = content.partition(marker)
        body, d = ground_text(
            head,
            texts_by_id,
            visible,
            numeric_on,
            extra_text=state.get("query", ""),
        )

        if sep:
            tail_clean = (tail or "").strip()

            if numeric_on and tail_clean and extract_quantities(tail_clean):
                print(
                    "[ground] warning: ungrounded background tail contains numeric quantities. "
                    "Marker removed; tail preserved pending grounding policy."
                )

            if tail_clean:
                body = body + "\n\n" + tail_clean
        bodies.append(body)
        drops.extend(d)
        
    llm_on = getattr(settings, "CITATION_SUPPORT_CHECK_ENABLED", True) and (
        not is_normal or getattr(settings, "CITATION_SUPPORT_CHECK_NORMAL", False)
    )
    if llm_on:
        timeout = getattr(settings, "CITATION_SUPPORT_TIMEOUT", 12)
        checker = get_llm(temperature=0, task="fast")
        def _invoke_json(system: str, user: str):
            return checker.invoke_json_mode(
                [SystemMessage(content=system), HumanMessage(content=user)],
                config={"timeout": timeout},
            )
        bodies, d = verify_support(
            bodies,
            texts_by_id,
            _invoke_json,
            strict=getattr(settings, "CITATION_SUPPORT_STRICT", False),
        )
        drops.extend(d)
    for sec, body in zip(sections, bodies):
        words = len(re.sub(r"\[paper_id=\d+\]", "", body).split())
        abstained = False

        if not body.strip() or ((sec.get("content") or "").strip() and words < 12):
            body = ABSTAIN_TEXT
            abstained = True

        sec["content"] = body
        sec["abstained"] = abstained
        sec["cited_paper_ids"] = extract_paper_ids(body)
    print(f"[ground] dropped/adjusted {len(drops)} claim(s)")
    for d in drops:
        print(f"[ground]   - {d['reason']}: {d['sentence']}")
    return sections


def _clean_content(text):
    text = _normalize_citation_artifacts(text)
    text = _normalize_latex_delimiters(text) 
    if not text:
        return ""

    text = _strip_internal_monologue(text)
    text = _sanitize_preserving_math(text)

    text = re.sub(
        r"(\$\$.*?\$\$)",
        r"\n\n\1\n\n",
        text,
        flags=re.DOTALL,
    )
    text = _DISCLAIMER_RE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _sanitize_preserving_math(text: str) -> str:
    """
    Sanitize text while preserving LaTeX math blocks exactly.

    1. Replace LaTeX blocks with placeholders.
    2. Call sanitize_for_web().
    3. Restore original LaTeX blocks.
    """
    text = _normalize_latex_delimiters(text)
    if not text:
        return ""

    math_blocks: list[str] = []

    def _stash(match):
        math_blocks.append(match.group(0))
        return f"@@MATH_BLOCK_{len(math_blocks) - 1}@@"

    protected = _MATH_DISPLAY_RE.sub(_stash, text)
    protected = _MATH_INLINE_RE.sub(_stash, protected)
    protected = _CITE_MARKER_RE.sub(_stash, protected)
    protected = _repair_numeric_citations(protected)
    sanitized = sanitize_for_web(protected)

    for i, block in enumerate(math_blocks):
        sanitized = sanitized.replace(f"@@MATH_BLOCK_{i}@@", block)

    return sanitized


def _strip_leading_title(text: str, title: str) -> str:
    norm = lambda s: re.sub(r"[#*_:\s]+", " ", s).strip().lower()
    t, lines = norm(title), (text or "").split("\n")
    while lines and norm(lines[0]) in ("", t):
        lines.pop(0)
    return "\n".join(lines).strip()


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
            "findings": (p.get("summary") or p.get("text") or "")[:900],
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
            f"- Heading: ## {m['title']}\n"
            f"  Goal: {m['purpose']}\n"
            f"  Target length: ~{m.get('target_words', 180)} words"
        )

    evidence_lines = []

    for m in batch_modules:
        e = evidence_map.get(m["module_id"], {})

        evidence_lines.append(
            f"- {m['module_id']}: status={e.get('evidence_status', 'none')}, "
            f"allowed_paper_ids={','.join([str(x) for x in e.get('paper_ids', []) if str(x) in _visible_ids_from_block(paper_block)][:6]) or 'none'}, "
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
        "\nSTRICT ANTI-REPETITION RULE:\n"
        "Do NOT generate identical comparison tables, executive summaries, or verdicts in every section.\n"
        "Only generate a markdown table if the specific module goal explicitly requires it.\n"
        "Never repeat the same bullet points or core arguments across different modules.\n"
        "If a fact was already covered in a previous section, reference it briefly ('as shown above') instead of restating it.\n"
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
DEPTH & MATURITY ENFORCEMENT:
You are writing a mature, comprehensive research report, NOT a brief summary.
Focus on analytical depth, mechanism-level explanations, and evidence synthesis.
Do NOT pad the text with unnecessary data, repetitive sentences, or fluff just to increase length.
Write naturally and thoroughly until the topic is fully covered for the module's Goal.
"""

    style_block = GROUNDING_RULES + "\n\n" + PLAIN_LANGUAGE_RULES
    if _is_comparison_query(state.get("query", "")):
        style_block += "\n\n" + _comparison_rules("The Direct Answer section")

    return f"""
You are writing part of a dynamic research report.

{_mode_positioning(state.get('response_mode', 'normal'))}

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

Every used source must be cited.
If a sentence uses information from a paper, include [paper_id=N] in that sentence.
Do not silently use a retrieved source.
Cite a source only if it specifically supports the claim in that sentence.
Do not cite a source just because it was retrieved. One citation per specific claim, not a stack.

Origin/historical/canonical claims must cite the original primary source; do not cite a later interpretive paper for an original claim unless no primary source is available (and then label it as secondary evidence).

If evidence is weak/none, say so explicitly.
If policy allows first-principles reasoning, clearly state your assumptions in the prose (e.g., "Based on first principles, assuming X..."). Do not use literal "Inference:" labels.
If policy allows speculation, clearly frame it as a hypothesis or forward-looking projection in the prose. Do not use literal "Speculative:" labels.

For independent_analysis, tradeoffs, and risk_analysis, clearly separate factual evidence from your own logical inferences and final recommendations in your prose, but DO NOT use literal "Evidence:", "Inference:", or "Recommendation:" labels or headings. Write in natural, professional paragraphs.

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

{style_block}

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
        + "Return markdown only. Start each module with the exact level-2 heading "
        + "provided in the 'Heading' field above.\n"
        + "Do NOT output 'module_id', 'Goal:', 'Target length:', or any metadata labels.\n"
        + "Just write the heading and the content paragraphs below it.\n"
        + "Do NOT wrap in JSON. Do NOT use code fences."
    )
    full_prompt = _enforce_groq_request_budget(full_prompt, _section_max_tokens(state, plan))
    _record_seen_ids(state, full_prompt)
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

        raw = llm.invoke(messages, config={"timeout": timeout},
                 max_tokens=_section_max_tokens(state, plan))

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
        + "Return markdown only. Start each module with the exact level-2 heading "
        + "provided in the 'Heading' field above.\n"
        + "Do NOT output 'module_id', 'Goal:', 'Target length:', or any metadata labels.\n"
        + "Just write the heading and the content paragraphs below it.\n"
        + "Do NOT wrap in JSON. Do NOT use code fences."
    )
    full_prompt = _enforce_groq_request_budget(full_prompt, _section_max_tokens(state, plan))
    _record_seen_ids(state, full_prompt)
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
        cleaned = _strip_leading_title(cleaned, m["title"])
        cleaned = _dedupe_paragraphs(cleaned, dedupe_seen)
        cleaned = _rewrite_author_year_markers(cleaned, state.get("ranked_papers", []))
        cited_ids = extract_paper_ids(cleaned)

        display_content = _sanitize_preserving_math(cleaned)

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

        for chunk in llm.stream(messages, config={"timeout": timeout},
                        max_tokens=_section_max_tokens(state, plan)):
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
            cleaned = _strip_leading_title(cleaned, m0["title"])
            cleaned = _dedupe_paragraphs(cleaned, dedupe_seen)

            cited_ids = extract_paper_ids(cleaned)

            display_content = _sanitize_preserving_math(cleaned)

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

    missing = [m for m in batch_modules if m["module_id"] not in sections]

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
            cleaned = _strip_leading_title(cleaned, sec.get("title", ""))
            cleaned = _dedupe_paragraphs(cleaned, dedupe_seen)

            cited_ids = extract_paper_ids(cleaned)

            display_content = _sanitize_preserving_math(cleaned)

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
            content = _strip_leading_title(content, m["title"])

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


def _deterministic_section_fallback(m, papers, summaries, labels, state):
    if state.get("evidence_mode") == "uploaded":
        return (f"The uploaded document does not contain enough explicit content "
                f"to fully support this section ({m.get('title', '')}).")
    mid, title, query = m["module_id"], m.get("title", ""), state.get("query", "")
    rows = [(i, p, summaries.get(str(i), {})) for i, p in enumerate(papers[:4])]
    if not rows:
        return "No retrieved sources were available for this section."
    has_direct = any((s.get("evidence_type") or "") == "direct" for _, _, s in rows)
    if mid == "key_concepts":
        lines = [f"- **{(p.get('title') or 'Source').strip()}** [paper_id={i}]: "
                 f"{(s.get('findings') or p.get('summary') or '')[:220]}" for i, p, s in rows]
        return f"Core concepts for \"{query}\" as covered by the retrieved sources:\n" + "\n".join(lines)
    if mid == "limitations":
        return (f"This report synthesizes {len(papers)} retrieved source(s) "
                f"(most relevant: [paper_id={rows[0][0]}]). Conclusions are bounded by what these "
                f"sources report; details absent from them (head-to-head comparisons, exact "
                f"quantitative figures, deployment specifics) remain uncertain.")
    lines = [f"- **{(p.get('title') or 'Source').strip()}** [paper_id={i}]: "
             f"{(s.get('findings') or p.get('summary') or '')[:220]}" for i, p, s in rows]
    lead = (f"Sources underpinning {title}:\n" if has_direct
            else f"Retrieved sources most relevant to {title}:\n")
    tail = ("" if has_direct else
            "\n\n*Note: direct evidence for this section is limited; treat as provisional.*")
    return lead + "\n".join(lines) + tail


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
        "architecture",
        "derivation",
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

    with ThreadPoolExecutor(max_workers=1) as ex:
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

    with ThreadPoolExecutor(max_workers=1) as ex:
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

Start with a direct, unlabeled opening paragraph that answers the question.
Then, use these exact bold labels for the rest of the response:
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
            max_tokens=2048,
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
            f"The available evidence is limited, but the top retrieved source provides some insight.\n\n"
            f"**Evidence:** [paper_id=0] {first.get('title', 'Untitled')}: {abstract}\n\n"
            f"**Limitations:** Only limited evidence could be retrieved quickly."
        )
    content = re.sub(
        r"(?im)^\s*\*\*Limitations:\*\*\s*",
        "",
        content,
    ).strip()

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
    return []


def _select_references(
    references: list[dict],
    cited_ref_ids: set[int],
    plan: dict,
    papers: list[dict],
    summaries: dict,
    target_k: int | None = None,
) -> list[dict]:
    """Only papers that are actually cited. No padding with retrieved-but-uncited ones."""
    if plan.get("reference_policy", "standard") == "none":
        return []
    return [r for r in references if r.get("id") in cited_ref_ids]


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
    abstained_parts = []

    for s in sections:
        title = s.get("title") or MODULE_LIBRARY.get(
            s.get("module_id"),
            {},
        ).get("title", "Section")

        content = _clean_content(s.get("content", ""))
        if not content:
            continue

        if s.get("abstained") or content.strip() == ABSTAIN_TEXT:
            abstained_parts.append((title, content))
            continue

        content = _strip_leading_title(content, title)
        if not content:
            continue

        parts.append((title, content))

    if parts:
        if len(parts) == 1:
            return parts[0][1].strip()

        return "\n".join(f"## {t}\n\n{c}\n" for t, c in parts).strip()

    return _EMPTY_ANSWER_FALLBACK


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
                max_tokens=2048,
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
            "**Short answer:** I could not find enough relevant research to answer "
            "this reliably.\n\n"
            "**What's uncertain:** No usable studies came back for this question. "
            "Try rephrasing it, or switch to Researched mode for a wider search."
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
    state["_visible_paper_ids"] = _visible_ids_from_block(paper_block)

    query = state.get("query", "")

    comparison_block = _comparison_rules("The Short answer") if _is_comparison_query(query) else ""
    length_hint = (
        "Length: 500 to 800 words."
        if _is_technical_derivation(query, None)
        else "Length: 350 to 550 words."
    )

    prompt = f"""
USER QUERY:
{query}

{conversation_block(state)}

{format_override(state)}

{_evidence_mode_instruction(state.get('evidence_mode', 'literature'))}

AVAILABLE SOURCES:
{paper_block or "(no retrieved sources)"}

{_answer_spec_context(state, state.get('evidence_matrix') or {})}

You are Direct Mode: research assistance on demand.
You support academic writing by giving a direct, clear, source-supported answer.

{_mode_positioning('normal')}

{GROUNDING_RULES}

{PLAIN_LANGUAGE_RULES}

{comparison_block}

{length_hint}

Structure (use these exact bold labels, no markdown headings; if a PRESENTATION REQUEST appears above, follow that request instead of this structure):
**Short answer:** 2-3 plain sentences that fully answer the question.
(If this is a comparison: put the verdict, the table and the "Choose ... when" bullets here.)
**What the research shows:** 3-5 bullets, each one claim with its citation [paper_id=N].
**What's uncertain:** include ONLY if a real gap affects the answer; otherwise omit this label.

Rules:
Do not output <think>, thinking, analysis, planning, or internal reasoning. Return only final user-facing content.
If the available sources are short or fragmented, give a shorter answer and say plainly what is missing. Do not expand with outside knowledge.
Answer the exact question. Do not add unrelated applications, surveys, or background unless required by the answer spec.
If the question asks about an original system, theory, algorithm, equation, or architecture, describe the original/canonical version first.
Never invent specific numbers. If quantifying without sources, prefix with "Inference:" or "Estimate:" and state assumptions.
Use only the available sources.
Cite sources using [paper_id=N] right after the claim they support.
Cite a source only when it directly supports the exact claim; do not cite a source merely because it was retrieved.
Origin/historical claims: cite the primary source when available; otherwise say the claim rests on secondary evidence.
For equations and derivations, use canonical notation, define every symbol, and do not drop scaling terms.
If required components are listed in the answer spec, explicitly include and explain each one.
Do not invent citations. Do not invent metrics. Do not overstate certainty.
If critical evidence is missing, say so plainly.
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
                        "Return markdown only. "
                        "Never output <think>, thinking, chain-of-thought, or internal reasoning."
                    )
                ),
                    HumanMessage(content=prompt),
                ],
            max_tokens=2048,
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
            f"**Short answer:** The evidence is limited, so treat this as provisional.\n\n"
            f"**What the research shows:**\n- [paper_id=0] {first.get('title', 'Untitled')}: {abstract}\n\n"
            f"**What's uncertain:** Only one source could be retrieved quickly."
        )

    if not content.strip():
        first = papers[0]

        content = (
            f"**Short answer:** The best match found is: {first.get('title', 'Untitled')}.\n\n"
            f"**What the research shows:**\n- [paper_id=0] {(first.get('summary') or '')[:400]}\n\n"
            f"**What's uncertain:** Only limited evidence could be retrieved quickly."
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


_UPLOADED_PAGE_MARKER_RE = re.compile(r"\[PAGE\s*\d+\]", re.IGNORECASE)


def _normalize_uploaded_excerpt(text: str) -> str:
    if not text:
        return ""

    text = _UPLOADED_PAGE_MARKER_RE.sub(" ", text)

    text = re.sub(r"^\s*\d+\s*$", " ", text, flags=re.MULTILINE)

    text = re.sub(r"\s+", " ", text)
    text = text.strip()

    if not text:
        return ""

    sentences = re.split(r"(?<=[.!?])\s+", text)
    seen = set()
    cleaned = []

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        key = sentence.lower()

        if len(key) >= 45 and key in seen:
            continue

        seen.add(key)
        cleaned.append(sentence)

    return " ".join(cleaned).strip()


_UPLOADED_QA_SYSTEM = (
    "You are a precise document analyst. Answer ONLY from the provided "
    "passages of the user's uploaded document. Never use outside knowledge. "
    "Never output thinking or internal reasoning. Return markdown only."
)


def _build_uploaded_passage_block(
    papers: list[dict],
    max_total_chars: int = 6000,
) -> str:
    parts = []
    used = 0

    for i, p in enumerate(papers):
        raw_text = (p.get("summary") or p.get("text") or "")[:1600]
        text = _normalize_uploaded_excerpt(raw_text)

        if not text:
            continue

        block = f"[paper_id={i}] {p.get('title', 'Uploaded document')}\n{text}"

        if used + len(block) > max_total_chars:
            break

        parts.append(block)
        used += len(block)

    return "\n\n".join(parts)


def _uploaded_passage_fallback(papers: list[dict]) -> str:
    lines = []
    used = 0

    for i, p in enumerate(papers[:3]):
        excerpt = _normalize_uploaded_excerpt((p.get("summary") or "")[:900])

        if not excerpt:
            continue

        lines.append(f"From the uploaded document [paper_id={i}]: {excerpt}")
        used += len(excerpt)

        if used > 1800:
            break

    return "\n\n".join(lines) or (
        "The uploaded document does not contain information relevant to "
        "this question."
    )


def _generate_uploaded_sections(
    papers: list[dict],
    summaries: dict[str, dict],
    state: AgentState,
    plan: dict,
    evidence_map: dict[str, dict],
    emitter,
    id_map: dict,
) -> list[dict]:
    """
    Dedicated uploaded-document generation.

    Normal mode:
      One direct answer.

    Researched / graph_research mode:
      Sectioned uploaded-document report using the strong model.
    """
    query = state.get("query", "")
    response_mode = state.get("response_mode", "normal")
    is_normal = response_mode == "normal"

    uploaded_task = (
        "strong"
        if response_mode in ("researched", "graph_research")
        else "default"
    )

    uploaded_max_tokens = (
        4096
        if response_mode in ("researched", "graph_research")
        else 2048
    )

    print(
        f"[summarize:uploaded] response_mode={response_mode} "
        f"task={uploaded_task} max_tokens={uploaded_max_tokens}"
    )

    passage_block = _build_uploaded_passage_block(papers)

    if not papers or not passage_block:
        content = (
            "The uploaded document does not contain information relevant to "
            "this question."
        )
        sec = {
            "module_id": "direct_answer",
            "title": "Direct Answer",
            "content": content,
            "cited_paper_ids": [],
            "evidence_status": "none",
            "confidence": "low",
        }

        if emitter is not None:
            emitter.submit("direct_answer", f"## Direct Answer\n\n{content}\n")

        return [sec]

    if is_normal:
        document_map = state.get("document_map", "No document structure or table of contents was detected.")
        prompt = (
            f"USER QUESTION:\n{query}\n\n"
            f"{conversation_block(state)}\n\n"
            f"{document_map}\n\n"
            f"DOCUMENT PASSAGES (from the user's uploaded document, most relevant first):\n"
            f"{passage_block}\n\n"
            f"Write a complete answer using ONLY the passages above.\n"
            f"CRITICAL CLOSED-BOOK RULES:\n"
            f"1. NO OUTSIDE KNOWLEDGE: You are strictly forbidden from using sector averages, lifecycle assumptions, or first-principles inference. If a number, metric, or comparison is not explicitly written in the passages above, DO NOT INVENT IT.\n"
            f"2. RESPECT DOCUMENT SCOPE: Look at the DOCUMENT STRUCTURE. Do not assume a chapter covers something its headings do not mention.\n"
            f"3. EXPLICIT OMISSIONS: If the document lacks a comparison or specific data, state clearly that the document does not provide it.\n\n"
            f"Rules:\n"
            f"- Address EVERY part of the question.\n"
            f"- Cite passages as [paper_id=N].\n"
            f"- Use the document's own facts, names, numbers, and examples.\n"
            f"- If something is not covered, say so in one sentence; never invent.\n"
            f"- Write 400-700 words: an unlabeled opening paragraph that directly "
            f"answers the question, then bold labels **Evidence:** and **Limitations:**."
        )

        content = None

        messages = [
            SystemMessage(content=_UPLOADED_QA_SYSTEM),
            HumanMessage(content=prompt),
        ]

        try:
            llm = get_llm(temperature=0, task=uploaded_task)
            raw = llm.invoke(
                messages,
                max_tokens=uploaded_max_tokens,
                config={"timeout": settings.REPORT_SECTION_TIMEOUT_DEEP},
            )
            content = _clean_content(
                raw.content if hasattr(raw, "content") else str(raw)
            )
        except Exception as e:
            print(f"[summarize:uploaded] answer failed: {type(e).__name__}: {e}")

        if (not content or len(content) < 120) and uploaded_task != "strong":
            print(
                "[summarize:uploaded] primary uploaded answer was short/empty; "
                "retrying once with task=strong"
            )

            try:
                retry_llm = get_llm(temperature=0, task="strong")
                raw = retry_llm.invoke(
                    messages,
                    max_tokens=uploaded_max_tokens,
                    config={"timeout": settings.REPORT_SECTION_TIMEOUT_DEEP},
                )
                retry_content = _clean_content(
                    raw.content if hasattr(raw, "content") else str(raw)
                )

                if retry_content and len(retry_content) >= 120:
                    content = retry_content
            except Exception as e:
                print(
                    f"[summarize:uploaded] strong retry failed: "
                    f"{type(e).__name__}: {e}"
                )

        if not content or len(content) < 120:
            print(
                f"[summarize:uploaded] SHORT/EMPTY content, falling back. "
                f"len={len(content) if content else 0} repr={content!r}"
            )
            content = _uploaded_passage_fallback(papers)

        sec = {
            "module_id": "direct_answer",
            "title": "Direct Answer",
            "content": content,
            "cited_paper_ids": extract_paper_ids(content),
            "evidence_status": "strong" if extract_paper_ids(content) else "mixed",
            "confidence": "medium",
        }

        if emitter is not None:
            display = _sanitize_preserving_math(
                rewrite_inline_citations(content, id_map)
            )
            emitter.submit("direct_answer", f"## Direct Answer\n\n{display}\n")

        return [sec]
        
    batch_modules = [
        m
        for m in plan.get("modules", [])
        if m.get("module_id") not in ("references", "confidence_uncertainty")
    ] or [{"module_id": "direct_answer", "title": "Direct Answer"}]

    titles = "\n".join(f"## {m['title']}" for m in batch_modules)

    document_map = state.get("document_map", "No document structure or table of contents was detected.")
    
    prompt = (
        f"USER QUESTION:\n{query}\n\n"
        f"{conversation_block(state)}\n\n"
        f"{document_map}\n\n"
        f"RELEVANT PASSAGES (from the user's uploaded document):\n"
        f"{passage_block}\n\n"
        f"Write a report using STRICTLY AND ONLY the passages above with EXACTLY these section headings:\n"
        f"{titles}\n\n"
        f"CRITICAL CLOSED-BOOK RULES:\n"
        f"1. NO OUTSIDE KNOWLEDGE: You are strictly forbidden from using sector averages, lifecycle assumptions, or first-principles inference. If a number, metric, or comparison is not explicitly written in the passages above, DO NOT INVENT IT.\n"
        f"2. NO 'UNSUPPORTED' TABLES: Do not create tables of metrics and label them 'Unsupported' or 'Inferred'. If the data is not in the text, simply write: 'The provided document does not contain quantitative data on [metric].'\n"
        f"3. RESPECT DOCUMENT SCOPE: Look at the DOCUMENT STRUCTURE. If a chapter is titled 'Environmental Impact' but the headings show it only covers 'Indoor Pollutants' and 'Battery Hazards', do not assume it covers lifecycle GHG emissions. Report exactly what the chapters cover.\n"
        f"4. EXPLICIT OMISSIONS: If the user asks for a comparison (e.g., renewable vs non-renewable) and the document lacks this comparison, state clearly: 'The document describes X but does not provide a comparative analysis of Y.'\n"
        f"5. DIRECT QUOTES: Where the document makes specific admissions (e.g., 'wind power does produce some pollution' during manufacturing), quote or closely paraphrase them rather than generalizing.\n\n"
        f"SECTION INSTRUCTIONS:\n"
        f"- Direct Answer 60-120 words; other sections 120-300 words each.\n"
        f"- Cite passages as [paper_id=N].\n"
        f"- If a section has no supporting passage content, state that the document does not cover it.\n"
        f"- No References section. No thinking."
    )

    sections: dict[str, dict] = {}

    try:
        llm = get_llm(temperature=0, task=uploaded_task)
        raw = llm.invoke(
            [
                SystemMessage(content=_UPLOADED_QA_SYSTEM),
                HumanMessage(content=prompt),
            ],
            max_tokens=uploaded_max_tokens,
            config={"timeout": settings.REPORT_SECTION_TIMEOUT_DEEP},
        )

        raw_content = raw.content if hasattr(raw, "content") else str(raw)

        if raw_content and len(raw_content.strip()) >= 80:
            sections = _parse_plain_sections(batch_modules, raw_content)
        else:
            print(
                "[summarize:uploaded] researched report returned short/empty content; "
                f"len={len(raw_content or '')}"
            )

    except Exception as e:
        print(
            f"[summarize:uploaded] section generation failed: "
            f"{type(e).__name__}: {e}"
        )

    for m in batch_modules:
        mid = m["module_id"]

        if mid in sections:
            continue

        if mid in ("direct_answer", "research_findings"):
            content = _uploaded_passage_fallback(papers)
        else:
            content = (
                f"The uploaded document provides limited detail for this "
                f"section ({m['title']})."
            )

        sections[mid] = {
            "module_id": mid,
            "title": m["title"],
            "content": content,
            "cited_paper_ids": extract_paper_ids(content),
            "evidence_status": "mixed",
            "confidence": "low",
        }

    ordered = []

    for m in batch_modules:
        sec = sections[m["module_id"]]
        sec["content"] = _clean_content(sec.get("content", ""))
        sec["content"] = re.sub(
            r"(?im)^\s*\*\*Limitations:\*\*\s*",
            "",
            sec["content"],
        ).strip()
        ordered.append(sec)

        if emitter is not None:
            display = _sanitize_preserving_math(
                rewrite_inline_citations(sec["content"], id_map)
            )
            emitter.submit(
                sec["module_id"],
                f"## {sec['title']}\n\n{display}\n",
            )

    return ordered


def summarize_node(state: AgentState) -> AgentState:
    papers = state.get("ranked_papers", [])
    plan = state.get("report_plan") or default_report_plan(state)

    state["_user_numeric_tokens"] = user_numeric_tokens(state.get("query", ""))

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
        state["_visible_paper_ids"] = set()
        emitter = None
        if streaming_enabled:
            emitter = _OrderedSectionEmitter([m["module_id"] for m in generative_modules],
                                            request_id, state.get("_cancel_check"), CitationNumberer(id_map))
        sections = _generate_sections_per_module(generative_modules, papers, summaries, state,
                                                evidence_map, guardrails, plan, emitter, depth)
        state["_visible_paper_ids"] = set(state.get("_seen_paper_ids", set()))
        sections = _expand_shallow_modules(sections, state, plan, papers, summaries)

    sections = _dedupe_sections(sections)


    for s_ in sections:
        s_["content"] = _rewrite_author_year_markers(s_.get("content", ""), papers)

    sections = _ground_sections(sections, papers, state)
    sections = _add_missing_numeric_citations(sections, papers, state)

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

    # TEMP DEBUG: remove once citations look right.
    _n = lambda t: len(re.findall(r"\[paper_id=\d+\]", t or ""))
    print(
        "[cite-debug] markers per section:",
        [(x.get("module_id"), _n(x.get("content"))) for x in sections],
        "| cited_paper_ids:", cited_paper_ids,
        "| refs kept:", len(selected_refs),
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
    answer_text = _strip_internal_monologue(answer_text)
    answer_text = _normalize_citation_artifacts(_normalize_latex_delimiters(answer_text))
    answer_text = _rewrite_author_year_markers(answer_text, papers)
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

    if not answer_text.strip():
        answer_text = _EMPTY_ANSWER_FALLBACK

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