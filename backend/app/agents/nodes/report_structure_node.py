import logging
import re
from typing import Literal, Optional
from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage
from app.agents.schemas import SectionContract
from app.agents.state import AgentState
from app.services.domain_router import classify_report_type
from app.services.llm_client import get_llm
from app.services.paper_search import search_openalex_async

log = logging.getLogger("report_studio")

SourceKind = Literal["user_guideline", "reporting_standard", "retrieved_papers", "llm_default"]


class RequestAnalysis(BaseModel):
    goal: Literal["analyze", "compare", "review", "propose", "describe", "evaluate"] = "analyze"
    work_type: Literal["experiment", "field_study", "survey", "literature_review",
                       "case_study", "business_analysis", "design_project",
                       "proposal", "other"] = "other"
    status: Literal["proposal", "completed"] = "completed"
    output_type: Literal["research_paper", "project_report", "field_report",
                         "proposal_document", "thesis_chapter", "general_report"] = "general_report"
    reasoning: str = ""


class StructureSection(BaseModel):
    section_id: str
    title: str
    level: int = 1
    purpose: str = ""
    reason: str = ""
    structure_source: SourceKind = "llm_default"
    evidence_required: bool = False
    target_words: int = 250
    data_scope: str = "all"


class ReportStructureDraft(BaseModel):
    analysis: RequestAnalysis = Field(default_factory=RequestAnalysis)
    structure_source: str = "llm_default"
    standard_used: Optional[str] = None
    sections: list[StructureSection] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


_ANALYSIS_PROMPT = """USER REQUEST:
{query}
GUIDELINE EXCERPT:
{guideline}
Decide, in one JSON object:
goal: analyze | compare | review | propose | describe | evaluate
work_type: experiment | field_study | survey | literature_review | case_study | business_analysis | design_project | proposal | other
status: "proposal" if the work is not yet done, else "completed"
output_type: research_paper | project_report | field_report | proposal_document | thesis_chapter | general_report
reasoning: one sentence.
Return ONLY the JSON object."""


def _fallback_analysis(query: str) -> RequestAnalysis:
    q = (query or "").lower()
    a = RequestAnalysis()
    if any(k in q for k in ("compare", "versus", " vs ")):
        a.goal = "compare"
    elif any(k in q for k in ("review", "survey of", "literature")):
        a.goal = "review"
    elif any(k in q for k in ("proposal", "propose", "plan to", "will be")):
        a.goal = "propose"
    if any(k in q for k in ("systematic review", "meta-analysis", "literature review")):
        a.work_type = "literature_review"
    elif any(k in q for k in ("field", "survey", "prevalence", "sampled", "collected")):
        a.work_type = "field_study"
    elif any(k in q for k in ("experiment", "trial", "lab", "tested")):
        a.work_type = "experiment"
    elif any(k in q for k in ("case report", "case study")):
        a.work_type = "case_study"
    elif any(k in q for k in ("business", "market", "kpi", "operational")):
        a.work_type = "business_analysis"
    if any(k in q for k in ("proposal", "propose", "plan to", "future work")):
        a.status = "proposal"
    if a.work_type == "literature_review":
        a.output_type = "research_paper"
    elif a.work_type == "field_study":
        a.output_type = "field_report"
    elif a.status == "proposal":
        a.output_type = "proposal_document"
    return a


async def analyze_request(query: str, guideline_text: str = "") -> RequestAnalysis:
    try:
        llm = get_llm(temperature=0, task="fast")
        raw = await _ainvoke_json(llm, query, guideline_text)
        return RequestAnalysis.model_validate(raw) if isinstance(raw, dict) else _fallback_analysis(query)
    except Exception as e:
        log.warning("analysis failed: %s", e)
        return _fallback_analysis(query)


async def _ainvoke_json(llm, query: str, guideline_text: str):
    import asyncio
    return await asyncio.to_thread(
        llm.invoke_json_mode,
        [SystemMessage(content="You analyze report requests. Return only JSON."),
         HumanMessage(content=_ANALYSIS_PROMPT.format(query=query[:4000],
                                                      guideline=(guideline_text or "none")[:1500]))],
        config={"timeout": 8},
    )


_GUIDE_RES = (
    re.compile(r"(?i)^\s*(?:chapter|section|unit|part|appendix)\s+\d+(?:\.\d+)*[.:]?\s+(?P<t>[A-Z][^\n]{2,90})\s*$"),
    re.compile(r"^\s*\d+(?:\.\d+)+\.?\s+(?P<t>[A-Z][^\n]{2,90})\s*$"),
    re.compile(r"^\s*(?P<t>[A-Z][A-Z\s&,:()/'\-]{6,70})\s*$"),
)
_SKIP_HEADINGS = {"table of contents", "contents", "abstract", "title page", "acknowledgement", "acknowledgements"}


def _parse_guideline_headings(text: str) -> list[str]:
    if not (text or "").strip():
        return []
    out: list[tuple[str, bool]] = []
    seen: set[str] = set()
    for line in text.splitlines():
        s = line.strip()
        if not s or len(s) > 90 or s.endswith((":", ";", "=", "->", ",")):
            continue
        if len(s.split()) > 12:
            continue
        for rx in _GUIDE_RES:
            m = rx.match(line)
            if not m:
                continue
            t = " ".join(m.group("t").split()).strip(" .")
            if t.lower() in _SKIP_HEADINGS or t.lower() in seen:
                break
            seen.add(t.lower())
            out.append((t, rx is _GUIDE_RES[0]))
            break
        if len(out) >= 80:
            break
    chapters = [t for t, is_ch in out if is_ch]
    if len(chapters) >= 3:
        return chapters[:15]
    heads = [t for t, _ in out][:15]
    return heads if len(heads) >= 3 else []


_EV_KEYS = ("result", "finding", "discussion", "comparison", "analysis",
            "evaluation", "method", "material", "statement", "reconciliation")


def _ev(title: str) -> bool:
    t = title.lower()
    if t == "references":
        return True
    return any(k in t for k in _EV_KEYS)


def _std_sections(name: str, spec: list[tuple[str, str, bool, int]]) -> list[StructureSection]:
    return [
        StructureSection(
            section_id=_slug(t, i + 1), title=t, purpose=p,
            reason=f"Required by the {name} reporting standard for this type of work.",
            structure_source="reporting_standard", evidence_required=e, target_words=w,
        )
        for i, (t, p, e, w) in enumerate(spec)
    ]


def _match_standard(query: str, a: RequestAnalysis) -> tuple[str, list[StructureSection]] | None:
    q = (query or "").lower()
    if any(k in q for k in ("systematic review", "meta-analysis", "meta analysis")):
        return "PRISMA", _std_sections("PRISMA", [
            ("Introduction", "Rationale and explicit objectives of the review.", False, 300),
            ("Methods", "Eligibility criteria, information sources, search strategy, synthesis methods.", False, 400),
            ("Results", "Study selection, study characteristics, synthesis of findings.", True, 500),
            ("Discussion", "Interpretation, limitations of evidence, conclusions.", True, 350),
            ("References", "Cited sources.", True, 0),
        ])
    if any(k in q for k in ("randomized controlled", "randomised controlled", "rct")):
        return "CONSORT", _std_sections("CONSORT", [
            ("Introduction", "Background and objectives of the trial.", False, 250),
            ("Methods", "Trial design, participants, interventions, outcomes, sample size, randomization.", False, 400),
            ("Results", "Participant flow, baseline data, outcomes and estimation.", True, 500),
            ("Discussion", "Interpretation, generalizability, overall evidence.", True, 350),
            ("References", "Cited sources.", True, 0),
        ])
    if any(k in q for k in ("cohort", "case-control", "cross-sectional", "observational", "prevalence")):
        return "STROBE", _std_sections("STROBE", [
            ("Introduction", "Background and objectives.", False, 250),
            ("Methods", "Study design, setting, participants, variables, data sources, statistical methods.", False, 400),
            ("Results", "Participants, descriptive data, main results.", True, 500),
            ("Discussion", "Key results, limitations, interpretation, generalizability.", True, 350),
            ("References", "Cited sources.", True, 0),
        ])
    if a.status == "completed" and a.work_type in ("experiment", "field_study"):
        return "IMRaD", _std_sections("IMRaD", [
            ("Introduction", "Context, rationale and objectives of the study.", False, 300),
            ("Materials and Methods", "Study design, sampling, data collection and analysis.", False, 400),
            ("Results", "Findings presented objectively, with tables where useful.", True, 500),
            ("Discussion", "Interpretation, comparison with literature, limitations.", True, 400),
            ("Conclusion", "What the study establishes and its significance.", False, 200),
            ("References", "Cited sources.", True, 0),
        ])
    return None


async def _structure_from_papers(query: str, a: RequestAnalysis) -> list[StructureSection] | None:
    try:
        rows = await search_openalex_async(query[:200], 6, False)
    except Exception as e:
        log.warning("structure probe search failed: %s", e)
        return None
    rows = [r for r in (rows or []) if r.get("title")][:6]
    if len(rows) < 3:
        return None
    block = "\n".join(
        f"- {r.get('title','')} | {r.get('venue') or r.get('source','')} | {str(r.get('published') or '')[:4]}"
        for r in rows
    )
    prompt = (
        f"WORK TYPE: {a.work_type} ({a.status}). OUTPUT: {a.output_type}.\n"
        f"SIMILAR RETRIEVED PAPERS:\n{block}\n"
        "List the 5-9 section headings that papers of this field and type typically use "
        "for this kind of work. JSON: {\"sections\":[{\"title\":str,\"purpose\":str,"
        "\"evidence_required\":bool}]} only."
    )
    try:
        llm = get_llm(temperature=0, task="fast")
        raw = llm.invoke_json_mode(
            [SystemMessage(content="You infer report skeletons from paper collections. Return only JSON."),
             HumanMessage(content=prompt)],
            config={"timeout": 10},
        )
        items = (raw or {}).get("sections", []) if isinstance(raw, dict) else []
    except Exception as e:
        log.warning("structure-from-papers LLM failed: %s", e)
        return None
    out: list[StructureSection] = []
    anchor = rows[0].get("title", "")[:70]
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            continue
        t = str(it.get("title") or "").strip()
        if not t or len(t) > 90:
            continue
        out.append(StructureSection(
            section_id=_slug(t, i + 1), title=t,
            purpose=str(it.get("purpose") or f"Standard section for this paper type.")[:400],
            reason=f"Typical structure in similar retrieved papers (e.g. “{anchor}”).",
            structure_source="retrieved_papers",
            evidence_required=bool(it.get("evidence_required")) or _ev(t),
            target_words=0 if t.lower() == "references" else 300,
        ))
        if len(out) >= 10:
            break
    return out or None


async def _llm_default(query: str, a: RequestAnalysis) -> list[StructureSection]:
    prompt = (
        f"REQUEST: {query[:3000]}\n"
        f"ANALYSIS: goal={a.goal}, work_type={a.work_type}, status={a.status}, output={a.output_type}.\n"
        "Propose a sensible 5-9 section outline (plus References) for the resulting document. "
        "JSON: {\"sections\":[{\"title\":str,\"purpose\":str,\"evidence_required\":bool,\"target_words\":int}]} only."
    )
    try:
        llm = get_llm(temperature=0, task="fast")
        raw = llm.invoke_json_mode(
            [SystemMessage(content="You plan report structures. Return only JSON."),
             HumanMessage(content=prompt)],
            config={"timeout": 10},
        )
        items = (raw or {}).get("sections", []) if isinstance(raw, dict) else []
    except Exception as e:
        log.warning("llm default structure failed: %s", e)
        items = []
    out: list[StructureSection] = []
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            continue
        t = str(it.get("title") or "").strip()
        if not t:
            continue
        try:
            words = int(it.get("target_words") or 300)
        except Exception:
            words = 300
        out.append(StructureSection(
            section_id=_slug(t, i + 1), title=t[:90],
            purpose=str(it.get("purpose") or "")[:400],
            reason="Proposed by Sykra as a sensible default for this request type.",
            structure_source="llm_default",
            evidence_required=bool(it.get("evidence_required")) or _ev(t),
            target_words=words,
        ))
        if len(out) >= 10:
            break
    if not out:
        out = [
            StructureSection(section_id="executive_summary", title="Executive Summary",
                             purpose="Key findings and conclusions.", reason="Default structure.",
                             structure_source="llm_default", target_words=250),
            StructureSection(section_id="introduction", title="Introduction",
                             purpose="Context and purpose.", reason="Default structure.",
                             structure_source="llm_default", target_words=250),
            StructureSection(section_id="body", title="Findings and Analysis",
                             purpose="Core content.", reason="Default structure.",
                             structure_source="llm_default", evidence_required=True, target_words=500),
            StructureSection(section_id="conclusion", title="Conclusion",
                             purpose="Summary and implications.", reason="Default structure.",
                             structure_source="llm_default", target_words=200),
        ]
    return out


def _slug(title: str, idx: int) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (title or "").lower()).strip("_")[:40]
    return s or f"section_{idx}"


def _finalize(sections: list[StructureSection]) -> list[StructureSection]:
    seen: set[str] = set()
    clean: list[StructureSection] = []
    for s in sections:
        if s.section_id in seen or not s.title.strip():
            continue
        seen.add(s.section_id)
        s.target_words = 0 if s.title.lower() == "references" else max(100, min(700, s.target_words or 250))
        clean.append(s)
        if len(clean) >= 12:
            break
    if not any(s.title.lower() == "references" for s in clean):
        clean.append(StructureSection(
            section_id="references", title="References", purpose="Cited sources.",
            reason="Every report ends with its cited sources.",
            structure_source=clean[0].structure_source if clean else "llm_default",
            evidence_required=True, target_words=0))
    return clean


async def build_structure_draft(query: str, guideline_text: str = "",
                                analysis: RequestAnalysis | None = None) -> ReportStructureDraft:
    analysis = analysis or await analyze_request(query, guideline_text)
    heads = _parse_guideline_headings(guideline_text or "")
    if heads:
        sections = [
            StructureSection(
                section_id=_slug(t, i + 1), title=t,
                purpose="Section required by the user's guideline or template.",
                reason=f"Heading taken from your provided guideline/template (“{t}”).",
                structure_source="user_guideline",
                evidence_required=_ev(t),
                target_words=0 if t.lower() == "references" else 300,
            )
            for i, t in enumerate(heads)
        ]
        return ReportStructureDraft(
            analysis=analysis, structure_source="user_guideline",
            sections=_finalize(sections),
            notes=[f"Followed {len(sections)} heading(s) from your guideline/template."])
    std = _match_standard(query, analysis)
    if std:
        name, sections = std
        return ReportStructureDraft(
            analysis=analysis, structure_source="reporting_standard",
            standard_used=name, sections=_finalize(sections),
            notes=[f"Applied the {name} reporting standard."])
    from_papers = await _structure_from_papers(query, analysis)
    if from_papers:
        return ReportStructureDraft(
            analysis=analysis, structure_source="retrieved_papers",
            sections=_finalize(from_papers),
            notes=["Structure inferred from similar retrieved papers."])
    default = await _llm_default(query, analysis)
    return ReportStructureDraft(
        analysis=analysis, structure_source="llm_default",
        sections=_finalize(default),
        notes=["No guideline, standard or paper-structure signal found; Sykra proposed a default."])


_NO_DATA = {"title", "introduction", "background", "context", "purpose_scope", "references"}


def _section_prohibitions(section_id: str) -> list[str]:
    if section_id in ("results", "findings", "statements", "summary", "body"):
        return ["Do not interpret results unless the section purpose explicitly allows it.",
                "Do not convert percentages into counts unless explicitly provided.",
                "Do not invent sample sizes or demographics.",
                "Do not compute expected totals or per-unit averages; restate listed discrepancies exactly."]
    if section_id in ("abstract", "executive_summary", "conclusion", "conclusions"):
        return ["Do not introduce new facts not present in earlier sections.",
                "Do not overstate findings.",
                "Do not add unsupported recommendations.",
                "Do not convert percentages into counts.",
                "Do not repeat sentences from other sections; summarise in new words."]
    if section_id in ("introduction", "background", "context"):
        return ["Do not describe the section itself.",
                "Do not state results, percentages, or data discrepancies; they belong in the findings section.",
                "Do not invent objectives, institutions, or acronym expansions."]
    if section_id in ("recommendations", "next_steps"):
        return ["No generic husbandry, treatment, hygiene, nutrition, or management advice.",
                "Only steps that follow from a stated finding or data gap.",
                "Do not invent schedules, frequencies, or thresholds."]
    if section_id == "methodology":
        return ["Do not invent methods, instruments, sampling procedures, or analysis techniques."]
    return ["Do not invent facts.", "Do not cite unsupported evidence."]


def structure_to_plan(sections: list[StructureSection]) -> list[dict]:
    return [
        {
            "section_id": s.section_id, "title": s.title, "purpose": s.purpose,
            "evidence_required": s.evidence_required, "target_words": s.target_words,
            "data_scope": s.data_scope or ("none" if s.section_id in _NO_DATA else "all"),
            "order": (i + 1) * 100, "level": s.level,
            "reason": s.reason, "structure_source": s.structure_source,
        }
        for i, s in enumerate(sections)
    ]


def structure_to_contracts(sections: list[StructureSection]) -> list[dict]:
    return [
        SectionContract(
            section_id=s.section_id, title=s.title, purpose=s.purpose,
            evidence_required=s.evidence_required,
            data_scope=s.data_scope or ("none" if s.section_id in _NO_DATA else "all"),
            target_words=s.target_words, required_citations=s.evidence_required,
            prohibited=_section_prohibitions(s.section_id), evidence_ids=[],
        ).model_dump()
        for s in sections
    ]


def detect_report_type(query: str, uploaded_content=None) -> str | None:
    extra = " ".join((c.get("summary") or c.get("text") or "")[:300]
                     for c in (uploaded_content or [])[:3])
    return classify_report_type(f"{query or ''}\n{extra}".strip())


def build_brief(query: str, evidence_mode: str, report_type: str, title: str,
                analysis: RequestAnalysis | None = None) -> dict:
    scope = {"uploaded": "uploaded_only", "blended": "blended",
             "literature": "literature_only"}.get(evidence_mode, "none")
    return {
        "purpose": query[:500], "audience": "academic", "deliverable": "report",
        "report_type": report_type or "general", "execution_path": "standard",
        "constraints": [
            "Use user-provided figures exactly as written.",
            "Never round, convert, or normalize user-provided values.",
            "Never invent numbers, counts, sample sizes, institutions, or results.",
            "State explicitly when required evidence is not available.",
        ],
        "information_needs": [query[:300]] if query else [],
        "data_scope": scope, "working_title": title,
    }


_FALLBACK_SECTIONS = [
    StructureSection(section_id="executive_summary", title="Executive Summary",
                     purpose="Key findings and conclusions.", reason="Fallback structure.",
                     evidence_required=False, target_words=250),
    StructureSection(section_id="introduction", title="Introduction",
                     purpose="Context and purpose.", reason="Fallback structure.", target_words=250),
    StructureSection(section_id="body", title="Findings and Analysis",
                     purpose="Core content.", reason="Fallback structure.",
                     evidence_required=True, target_words=500),
    StructureSection(section_id="conclusion", title="Conclusion",
                     purpose="Summary and implications.", reason="Fallback structure.", target_words=200),
    StructureSection(section_id="references", title="References",
                     purpose="Cited sources.", reason="Fallback structure.",
                     evidence_required=True, target_words=0),
]


def ensure_report_structure(state: AgentState) -> dict:
    """Graph safety net: report runs arrive with an approved structure; if one
    is missing for any reason, build a deterministic minimal one."""
    if state.get("report_section_plan") and state.get("report_section_contracts"):
        return {}
    sections = [s.model_copy(deep=True) for s in _FALLBACK_SECTIONS]
    title = state.get("report_title") or " ".join((state.get("query") or "Report").split())[:110]
    return {
        "report_type": state.get("report_type") or "general",
        "report_audience": state.get("report_audience") or "academic",
        "report_title": title,
        "report_section_plan": structure_to_plan(sections),
        "report_section_contracts": structure_to_contracts(sections),
        "report_brief": build_brief(state.get("query", ""), state.get("evidence_mode", "literature"),
                                    state.get("report_type") or "general", title),
        "report_revision_count": 0,
    }