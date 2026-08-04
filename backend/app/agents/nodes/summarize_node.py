import re
import json
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
Display math:
$$y = mx + b$$
Define symbols in prose.
CURRENCY RULE:
Never use the $ symbol for currency amounts.
Write "USD 48/MWh" or "48 USD/MWh" instead of "$48/MWh".
CITATION RULE:
Use ONLY ASCII square brackets for citations: [paper_id=N].
Never use fullwidth brackets like 【paper_id=N】.
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


def _clean_content(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


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
    return any(m.get("module_id") == module_id for m in plan.get("modules", []))


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
                f"Title: {p.get('title', '')}\n"
                f"Key contribution: {s.get('key_contribution', '')}\n"
                f"Findings: {s.get('findings', '')}\n"
                f"Metrics: {metrics}"
            )
        else:
            abstract = p.get("summary") or p.get("text") or ""
            parts.append(
                f"[paper_id={i}] Title: {p.get('title', '')}\n"
                f"Abstract: {abstract[:max_abstract]}"
            )
    return "\n\n".join(parts)


def _reclassify_evidence_types(papers: list[dict], summaries: dict, state: AgentState) -> dict:
    terms = _important_query_terms(state)
    direct_phrases = (
        "directly address", "directly study", "directly investigat",
        "proposes", "introduces", "presents",
        "framework for", "method for", "model for",
    )
    supporting_phrases = (
        "related", "similar", "applies", "uses",
        "dataset", "background", "supports",
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
    counts = {"direct": 0, "supporting": 0, "background": 0}
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
    direct_ids = [sid for sid, s in summaries.items() if s.get("evidence_type") == "direct"]
    supporting_ids = [sid for sid, s in summaries.items() if s.get("evidence_type") == "supporting"]
    background_ids = [sid for sid, s in summaries.items() if s.get("evidence_type") == "background"]
    understanding = state.get("query_understanding") or {}
    comparison_candidates = []
    comparison_candidates.extend(understanding.get("methods_techniques") or [])
    comparison_candidates.extend(understanding.get("entities") or [])
    comparison_candidates = list(dict.fromkeys([c.strip() for c in comparison_candidates if c and c.strip()]))
    keyword_map = {
        "risk_analysis": ["risk", "failure", "safety", "adverse", "side effect", "threat", "limitation"],
        "tradeoffs": ["tradeoff", "trade-off", "pros", "cons", "advantage", "disadvantage", "comparison"],
        "cost_resources": ["cost", "budget", "compute", "gpu", "memory", "latency", "resource", "price"],
        "implementation_plan": ["implement", "deploy", "pipeline", "architecture", "build", "practice"],
        "timeline_roadmap": ["roadmap", "timeline", "milestone", "phase", "future"],
        "future_outlook": ["future", "forecast", "prediction", "trend", "outlook", "scenario"],
        "alternatives": ["alternative", "baseline", "other", "approach", "method"],
    }
    for module in plan.get("modules", []):
        mid = module.get("module_id")
        entry = {
            "module_id": mid,
            "evidence_status": "none",
            "paper_ids": [],
            "notes": "",
        }
        if mid in ("references", "confidence_uncertainty"):
            entry["evidence_status"] = "not_applicable"
        elif mid in ("background", "key_concepts"):
            entry["paper_ids"] = (background_ids + supporting_ids + direct_ids)[:4]
            entry["evidence_status"] = "not_applicable"
            entry["notes"] = "Use background knowledge and retrieved context; cite only if directly useful."
        elif mid == "comparative_analysis":
            entry["paper_ids"] = (direct_ids + supporting_ids)[:6]
            entry["evidence_status"] = _status_from_paper_ids(entry["paper_ids"], summaries)
            if len(comparison_candidates) >= 2:
                entry["notes"] = f"Candidates: {', '.join(comparison_candidates[:6])}."
            else:
                entry["notes"] = "Infer comparison items from the query and evidence."
        elif mid in ("research_findings", "methodology"):
            entry["paper_ids"] = (direct_ids + supporting_ids)[:6]
            entry["evidence_status"] = _status_from_paper_ids(entry["paper_ids"], summaries)
        elif mid in keyword_map:
            matched = []
            kws = keyword_map[mid]
            for sid, s in summaries.items():
                text = " ".join([
                    str(s.get("key_contribution", "")),
                    str(s.get("findings", "")),
                    str(s.get("relevance_to_query", "")),
                ]).lower()
                if any(k in text for k in kws):
                    matched.append(sid)
            if matched:
                entry["paper_ids"] = matched[:6]
            else:
                entry["paper_ids"] = (direct_ids + supporting_ids)[:3]
            entry["evidence_status"] = _status_from_paper_ids(entry["paper_ids"], summaries)
        else:
            entry["paper_ids"] = (direct_ids + supporting_ids + background_ids)[:5]
            entry["evidence_status"] = _status_from_paper_ids(entry["paper_ids"], summaries)
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
    guardrail_text = "\n".join(f"- {g}" for g in guardrails) if guardrails else "- None"
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
    return f"""
You are writing part of a dynamic research report.
USER QUERY:
{state.get('query', '')}
REPORT DEPTH:
{plan.get('depth', 'medium')}
REASONING POLICY:
{plan.get('reasoning_policy', 'evidence_plus_analysis')}
{_evidence_mode_instruction(state.get('evidence_mode', 'literature'))}
DOMAIN GUARDRAILS:
{guardrail_text}
WRITE THESE MODULES EXACTLY:
{chr(10).join(module_lines)}
EVIDENCE STATUS:
{chr(10).join(evidence_lines)}
AVAILABLE SOURCES:
{paper_block or "(no retrieved sources)"}
{dedup_instruction}
CITATION RULES:
Use inline citations as [paper_id=N].
Only cite paper_ids that appear in AVAILABLE SOURCES.
Do not invent citations.
If evidence is weak/none, say so explicitly.
If policy allows first-principles reasoning, label it with "Inference:".
If policy allows speculation, label it with "Speculative:".
For independent_analysis, tradeoffs, risk_analysis, use:
Evidence:
Inference:
Recommendation:
FORMATTING RULES:
Return markdown content for each module.
Do NOT include the module title as a heading. The system will add headings.
Use bullets, short paragraphs, and tables where useful.
Keep each module near its target_words.
Do NOT create a References section.
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
    title_to_module = {}
    for m in batch_modules:
        title_to_module[m["title"].lower()] = m
        title_to_module[m["module_id"].replace("_", " ").lower()] = m
    used = set()
    for title, content in parsed:
        m = title_to_module.get(title.lower())
        if m and m["module_id"] not in used:
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
        used.add(batch_modules[0]["module_id"])
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
        SystemMessage(content="You are a modular research report writer. Return markdown only."),
        HumanMessage(content=full_prompt),
    ]
    try:
        llm = get_llm(temperature=0, task="strong")
        raw = llm.invoke(messages, config={"timeout": timeout})
        return _parse_plain_sections(batch_modules, raw.content)
    except Exception as e:
        print(f"[summarize] section batch generation failed: {type(e).__name__}: {e}")
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
) -> dict[str, dict]:
    """
    Streaming version: uses llm.stream(), splits on ## header boundaries,
    rewrites citations + sanitizes per section, pushes to ordered emitter.
    Returns partial results on stream error (caller retries missing).
    """
    cancel_check = state.get("_cancel_check")

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
        SystemMessage(content="You are a modular research report writer. Return markdown only."),
        HumanMessage(content=full_prompt),
    ]

    title_to_module = {}
    for m in batch_modules:
        title_to_module[m["title"].lower()] = m
        title_to_module[m["module_id"].replace("_", " ").lower()] = m

    def _emit_section(title: str, raw_content: str):
        m = title_to_module.get(title.lower())
        if not m:
            return None
        mid = m["module_id"]
        cleaned = _clean_content(raw_content)
        cited_ids = extract_paper_ids(cleaned)
        content = rewrite_inline_citations(cleaned, id_map)
        content = sanitize_for_web(content)
        if emitter is not None:
            emitter.submit(mid, f"## {m['title']}\n\n{content}\n")
        return {
            "module_id": mid,
            "title": m["title"],
            "content": content,
            "cited_paper_ids": cited_ids,
            "evidence_status": evidence_map.get(mid, {}).get("evidence_status", "mixed"),
            "confidence": "medium",
        }

    sections: dict[str, dict] = {}
    try:
        llm = get_llm(temperature=0, task="strong")
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
            cited_ids = extract_paper_ids(cleaned)
            content = rewrite_inline_citations(cleaned, id_map)
            content = sanitize_for_web(content)
            if emitter is not None:
                emitter.submit(m0["module_id"], f"## {m0['title']}\n\n{content}\n")
            sections[m0["module_id"]] = {
                "module_id": m0["module_id"],
                "title": m0["title"],
                "content": content,
                "cited_paper_ids": cited_ids,
                "evidence_status": evidence_map.get(m0["module_id"], {}).get("evidence_status", "mixed"),
                "confidence": "medium",
            }

    except Exception as e:
        print(f"[summarize] streaming batch failed, returning partial: {type(e).__name__}: {e}")

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
        batch_modules, paper_block, state, evidence_map, guardrails, plan, timeout,
    )
    missing = [m for m in batch_modules if m["module_id"] not in sections]
    if missing:
        print(f"[summarize] retrying {len(missing)} missing module(s): {[m['module_id'] for m in missing]}")
        retry_sections = _invoke_section_batch(
            missing, paper_block, state, evidence_map, guardrails, plan, timeout,
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
                "evidence_status": evidence_map.get(mid, {}).get("evidence_status", "none"),
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
) -> list[dict]:
    if not batch_modules:
        return []

    cancel_check = state.get("_cancel_check")
    sections = _stream_invoke_section_batch(
        batch_modules, paper_block, state, evidence_map,
        guardrails, plan, timeout, emitter, id_map,
    )

    missing = [m for m in batch_modules if m["module_id"] not in sections]
    if missing and not (cancel_check and cancel_check()):
        print(f"[summarize:stream] retrying {len(missing)} missing module(s)")
        retry = _invoke_section_batch(
            missing, paper_block, state, evidence_map,
            guardrails, plan, timeout,
        )
        for mid, sec in retry.items():
            cleaned = _clean_content(sec.get("content", ""))
            cited_ids = extract_paper_ids(cleaned)
            content = rewrite_inline_citations(cleaned, id_map)
            content = sanitize_for_web(content)
            sec["content"] = content
            sec["cited_paper_ids"] = cited_ids
            if emitter is not None:
                emitter.submit(mid, f"## {sec['title']}\n\n{content}\n")
        sections.update(retry)

    for m in batch_modules:
        mid = m["module_id"]
        if mid not in sections:
            placeholder = {
                "module_id": mid,
                "title": m["title"],
                "content": "No content could be generated for this section.",
                "cited_paper_ids": [],
                "evidence_status": evidence_map.get(mid, {}).get("evidence_status", "none"),
                "confidence": "low",
            }
            sections[mid] = placeholder
            if emitter is not None:
                emitter.submit(mid, f"## {m['title']}\n\n{placeholder['content']}\n")

    return [sections[m["module_id"]] for m in batch_modules]


def _split_batches(modules: list[dict], depth: str) -> list[list[dict]]:
    if depth == "low" or len(modules) <= 4:
        return [modules]
    core_ids = {
        "direct_answer", "executive_summary", "background",
        "key_concepts", "methodology", "research_findings",
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
            batches[0], paper_block, state, evidence_map,
            guardrails, plan, timeout,
        )
    sections = []
    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = {
            ex.submit(
                _generate_sections_batch,
                batch, paper_block, state, evidence_map,
                guardrails, plan, timeout,
            ): batch
            for batch in batches
        }
        for future in as_completed(futures):
            try:
                sections.extend(future.result())
            except Exception as e:
                print(f"[summarize] parallel section generation failed: {type(e).__name__}: {e}")
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
    if len(batches) == 1:
        return _generate_sections_batch_streaming(
            batches[0], paper_block, state, evidence_map,
            guardrails, plan, timeout, emitter, id_map,
        )
    sections: list[dict] = []
    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = {
            ex.submit(
                _generate_sections_batch_streaming,
                batch, paper_block, state, evidence_map,
                guardrails, plan, timeout, emitter, id_map,
            ): batch
            for batch in batches
        }
        for future in as_completed(futures):
            try:
                sections.extend(future.result())
            except Exception as e:
                print(f"[summarize:stream] parallel generation failed: {type(e).__name__}: {e}")
    if emitter is not None:
        emitter.flush_remaining()
    return sections


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


def _select_default_cited_ids(papers: list[dict], summaries: dict, plan: dict) -> list[str]:
    direct_ids = [sid for sid, s in summaries.items() if s.get("evidence_type") == "direct"]
    supporting_ids = [sid for sid, s in summaries.items() if s.get("evidence_type") == "supporting"]
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
) -> list[dict]:
    policy = plan.get("reference_policy", "standard")
    if policy == "none":
        return []
    max_refs = {
        "minimal": 3, "standard": 8, "research": 12, "documentation": 8,
    }.get(policy, 8)
    if cited_ref_ids:
        selected = [r for r in references if r.get("id") in cited_ref_ids]
    else:
        selected = []
    if not selected:
        direct_ids = [sid for sid, s in summaries.items() if s.get("evidence_type") == "direct"]
        supporting_ids = [sid for sid, s in summaries.items() if s.get("evidence_type") == "supporting"]
        preferred_paper_ids = direct_ids[:max_refs] + supporting_ids[:max_refs]
        link_to_ref = {r["link"]: r for r in references}
        for pid in preferred_paper_ids:
            if not pid.isdigit():
                continue
            idx = int(pid)
            if idx < len(papers):
                link = papers[idx].get("link")
                if link in link_to_ref:
                    selected.append(link_to_ref[link])
    if not selected:
        selected = references[:max_refs]
    seen = set()
    capped = []
    for r in selected:
        rid = r.get("id")
        if rid in seen:
            continue
        seen.add(rid)
        capped.append(r)
        if len(capped) >= max_refs:
            break
    return capped


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
    reasons.append(f"{direct} direct and {supporting} supporting papers")
    rels = []
    for p in papers[:6]:
        r = float(
            p.get("_relevance_orig") or p.get("_initial_sim")
            or p.get("final_score") or p.get("score") or 0.0
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
        points -= 1.25
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
        if mid in ("references", "confidence_uncertainty", "background", "key_concepts"):
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
    uncertainty = {"high": "low", "medium": "moderate", "low": "high"}.get(
        evidence_quality, "moderate"
    )
    explanation = "Evidence: " + "; ".join(reasons) + "."
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
        m["module_id"]: m.get("order", MODULE_LIBRARY.get(m["module_id"], {}).get("order", 9999))
        for m in plan.get("modules", [])
    }
    sections = sorted(sections, key=lambda s: order.get(s.get("module_id"), 9999))
    parts = []
    for s in sections:
        content = _clean_content(s.get("content", ""))
        if not content:
            continue
        title = s.get("title") or MODULE_LIBRARY.get(s.get("module_id"), {}).get("title", "Section")
        content = _strip_headers(content)
        parts.append(f"## {title}\n\n{content}\n")
    return "\n".join(parts).strip()


def summarize_node(state: AgentState) -> AgentState:
    llm = get_llm(temperature=0)
    papers = state.get("ranked_papers", [])
    plan = state.get("report_plan") or default_report_plan(state)
    depth = plan.get("depth", "low")
    generative_modules = [
        m for m in plan.get("modules", [])
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
    max_papers = 5 if depth == "low" else 8
    max_abstract = 500 if depth == "low" else 900
    paper_block = _build_paper_block(
        papers, summaries, max_abstract=max_abstract, max_papers=max_papers,
    )
    guardrails = plan.get("domain_guardrails", [])

    references = build_references(papers)
    if state.get("evidence_mode") == "uploaded":
        references = [r for r in references if r.get("source") == "user_upload"]
    id_map = paper_id_to_ref_id_map(papers, references)

    request_id = state.get("_request_id", "")
    streaming_enabled = bool(request_id and state.get("_streaming_enabled"))

    if streaming_enabled:
        ordered_ids = [m["module_id"] for m in generative_modules]
        emitter = _OrderedSectionEmitter(
            ordered_module_ids=ordered_ids,
            request_id=request_id,
            cancel_check=state.get("_cancel_check"),
        )
        sections = _generate_all_sections_streaming(
            generative_modules, paper_block, state, evidence_map,
            guardrails, plan, depth, emitter, id_map,
        )
    else:
        sections = _generate_all_sections(
            generative_modules, paper_block, state, evidence_map,
            guardrails, plan, depth,
        )

    cited_paper_ids = _collect_cited_paper_ids(sections, papers)
    if not cited_paper_ids:
        cited_paper_ids = _select_default_cited_ids(papers, summaries, plan)

    for s in sections:
        s["content"] = rewrite_inline_citations(_clean_content(s.get("content", "")), id_map)

    cited_ref_ids = set()
    for pid in cited_paper_ids:
        if pid in id_map:
            cited_ref_ids.add(id_map[pid])
    selected_refs = _select_references(references, cited_ref_ids, plan, papers, summaries)
    dynamic_confidence = _compute_dynamic_confidence(
        state, papers, summaries, sections, evidence_map, plan,
    )
    answer_text = _merge_sections(sections, plan)
    domain_caveat = state.get("domain_caveat")
    if guardrails:
        guardrail_text = " ".join(guardrails)
        domain_caveat = f"{guardrail_text} {domain_caveat}".strip() if domain_caveat else guardrail_text
    if state.get("low_confidence_results"):
        low_conf_note = (
            "Few strongly relevant papers were found, so the relevance threshold was relaxed. "
            "Treat this answer as a starting point rather than a comprehensive review."
        )
        domain_caveat = f"{domain_caveat} {low_conf_note}" if domain_caveat else low_conf_note
    answer_text = sanitize_for_web(answer_text)
    return {
        "summaries": summaries,
        "final_answer": answer_text.strip(),
        "coverage_gaps": [],
        "domain_caveat": domain_caveat,
        "references": selected_refs,
        "section_outputs": sections,
        "module_evidence_map": evidence_map,
        "dynamic_confidence": dynamic_confidence,
        "cited_paper_ids": cited_paper_ids,
        "report_plan": plan,
    }