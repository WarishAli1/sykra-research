"""
Builds VisualSpec from three distinct data-entry paths.
All grounded paths share ONE extraction function: extract_grounded_values().
A number only counts if it appears VERBATIM in source text.
Ambiguous attribution → unsupported, never guessed.
"""
from __future__ import annotations

import asyncio
import re
import uuid
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.visuals.schema import (
    VisualSpec,
    ChartPayload,
    ChartSeries,
    Provenance,
    ProvenanceKind,
    GroundingSummary,
    recompute_grounding,
)
from app.services.vector_store import vector_store


class SourceText(BaseModel):
    """One retrievable text block with full citation metadata."""
    text: str
    title: str
    url: str
    paper_id: Optional[int] = None
    ref_id: Optional[int] = None


class GroundedValue(BaseModel):
    label: str
    value: float
    unit: Optional[str] = None
    source_quote: str
    source: SourceText


class ExtractionResult(BaseModel):
    grounded: list[GroundedValue] = Field(default_factory=list)
    unsupported: list[str] = Field(default_factory=list)


_UNIT_PATTERN = (
    r"%|percent|billion|million|trillion|thousand|"
    r"USD|EUR|GBP|"
    r"GW|MW|kW|TW|TWh|MWh|kWh|GWh|"
    r"Gt|Mt|kt|tonnes?|tons?|"
    r"°C|degrees?|"
    r"dB|"
    r"km|miles?|meters?|hectares?|"
    r"per\s+(?:year|capita|hour|unit)|/year|annually|"
    r"accuracy|precision|recall|f1|auc|"
    r"latency|throughput|speedup|"
    r"parameters?|layers?|heads?"
)

_NUMBER_RE = re.compile(
    r"(?<!\d)"
    r"(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?:\s*(?:±)\s*\d+(?:\.\d+)?)?"
    r"\s*"
    r"(" + _UNIT_PATTERN + r")",
    re.IGNORECASE,
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _extract_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]


def extract_grounded_values(sources: list[SourceText]) -> ExtractionResult:
    """
    Shared extraction function for paths 2 and 3.
    Precision over recall: if there's ANY ambiguity about what a number
    refers to, it goes to unsupported — not guessed.
    """
    grounded: list[GroundedValue] = []
    unsupported: list[str] = []
    seen_values: set[tuple[float, str]] = set()

    for source in sources:
        sentences = _extract_sentences(source.text)

        for sentence in sentences:
            matches = list(_NUMBER_RE.finditer(sentence))
            if not matches:
                continue

            for match in matches:
                raw_number = match.group(1).replace(",", "")
                unit = match.group(2).strip()

                try:
                    value = float(raw_number)
                except ValueError:
                    continue

                key = (value, unit.lower())
                if key in seen_values:
                    continue
                seen_values.add(key)

                all_numbers_in_sentence = _NUMBER_RE.findall(sentence)
                distinct_units = {u.strip().lower() for _, u in all_numbers_in_sentence}
                if len(distinct_units) > 2:
                    unsupported.append(
                        f"Ambiguous: '{sentence[:80]}...' has multiple metrics"
                    )
                    continue

                if re.search(r"\[\d+\]|\[paper_id=\d+\]", sentence):
                    if unit.lower() not in ("%", "percent", "gw", "mw", "tw", "twh", "mwh"):
                        unsupported.append(
                            f"Skipped (citation ambiguity): '{sentence[:60]}...'"
                        )
                        continue

                label = _derive_label(sentence, unit)

                grounded.append(GroundedValue(
                    label=label,
                    value=value,
                    unit=unit,
                    source_quote=sentence,
                    source=source,
                ))

    return ExtractionResult(grounded=grounded, unsupported=unsupported)


def _derive_label(sentence: str, unit: str) -> str:
    """Extract a short label from the sentence context. Conservative."""
    m = re.search(
        r"([\w\s-]{3,30}?)\s+(?:of|is|was|reached|achieved|measured)\s+"
        + re.escape(unit),
        sentence,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()[:40]

    words = [w for w in sentence.split() if len(w) > 3][:4]
    return " ".join(words)[:40] or f"Value ({unit})"


def build_spec_from_user_data(
    session_id: str,
    title: str,
    chart_type: Literal["bar", "line", "pie", "scatter"],
    categories: list[str],
    series_data: list[dict],
    x_label: Optional[str] = None,
    y_label: Optional[str] = None,
) -> VisualSpec:
    """
    series_data: [{"label": "...", "values": [1,2,3], "unit": "..."}]
    Provenance = USER_PROVIDED for every value. No grounding question.
    """
    series = []
    for s in series_data:
        values = s.get("values", [])
        provenance = [
            Provenance(kind=ProvenanceKind.USER_PROVIDED)
            for _ in values
        ]
        series.append(ChartSeries(
            label=s.get("label", ""),
            values=values,
            unit=s.get("unit"),
            provenance=provenance,
        ))

    payload = ChartPayload(
        chart_type=chart_type,
        categories=categories,
        series=series,
        x_label=x_label,
        y_label=y_label,
    )

    spec = VisualSpec(
        visual_id=str(uuid.uuid4()),
        session_id=session_id,
        title=title,
        grounding=GroundingSummary(level="user_provided"),
        payload=payload,
    )
    spec.grounding = recompute_grounding(payload)
    return spec


def build_spec_from_prompt(
    session_id: str,
    title: str,
    chart_type: Literal["bar", "line", "pie", "scatter"],
    prompt: str,
) -> VisualSpec:
    """
    Chart draft from a user prompt.

    If numbers are present in the prompt, extract them using the same
    precision-biased extractor, but mark them USER_PROVIDED because the
    user supplied the prompt directly.

    If no numbers are present, return an illustrative fallback so the
    anti-hallucination contract remains intact.
    """
    sources = [
        SourceText(
            text=prompt[:3000],
            title="User prompt",
            url=f"session://{session_id}/prompt",
        )
    ]

    extraction = extract_grounded_values(sources)

    if not extraction.grounded:
        return _build_illustrative_spec(session_id, title, chart_type, prompt)

    categories = [g.label for g in extraction.grounded[:10]]
    values = [g.value for g in extraction.grounded[:10]]
    unit = extraction.grounded[0].unit if extraction.grounded else None

    provenance = []
    for g in extraction.grounded[:10]:
        provenance.append(
            Provenance(
                kind=ProvenanceKind.USER_PROVIDED,
                source_quote=g.source_quote,
                note="Extracted from user prompt",
            )
        )

    series = [
        ChartSeries(
            label=title or "Data",
            values=values,
            unit=unit,
            provenance=provenance,
        )
    ]

    payload = ChartPayload(
        chart_type=chart_type,
        categories=categories,
        series=series,
        y_label=unit,
    )

    spec = VisualSpec(
        visual_id=str(uuid.uuid4()),
        session_id=session_id,
        title=title,
        caption="Drafted from prompt. Confirm values before use.",
        grounding=GroundingSummary(
            level="user_provided",
            user_provided_count=len(values),
        ),
        payload=payload,
    )

    spec.grounding = recompute_grounding(payload)
    return spec


def build_spec_from_papers(
    session_id: str,
    title: str,
    chart_type: Literal["bar", "line", "pie", "scatter"],
    paper_ids: list[int],
    intent: str,
    ranked_papers: list[dict],
    references: list[dict],
) -> VisualSpec:
    """
    Reuses vector_store.get_full_text_for_paper — already-retrieved,
    already-trusted text. No new search call.
    """
    sources: list[SourceText] = []

    for pid in paper_ids:
        if pid < 0 or pid >= len(ranked_papers):
            continue
        paper = ranked_papers[pid]
        link = paper.get("link", "")
        full_text = vector_store.get_full_text_for_paper(link, session_id)
        if not full_text:
            full_text = paper.get("summary", "") or paper.get("text", "")

        ref_id = None
        for r in references:
            if r.get("link") == link:
                ref_id = r.get("id")
                break

        sources.append(SourceText(
            text=full_text[:3000],
            title=paper.get("title", ""),
            url=link,
            paper_id=pid,
            ref_id=ref_id,
        ))

    return _build_grounded_spec(
        session_id=session_id,
        title=title,
        chart_type=chart_type,
        sources=sources,
        intent=intent,
    )


def build_spec_from_web_search(
    session_id: str,
    title: str,
    chart_type: Literal["bar", "line", "pie", "scatter"],
    search_query: str,
    intent: str,
) -> VisualSpec:
    """
    Runs a live search (reuses paper_search / web_search as functions,
    NOT the LangGraph graph), then extracts with the same grounding rule.
    """
    sources = _run_search_sync(search_query)

    if not sources:
        return _build_illustrative_spec(session_id, title, chart_type, intent)

    return _build_grounded_spec(
        session_id=session_id,
        title=title,
        chart_type=chart_type,
        sources=sources,
        intent=intent,
    )


def build_spec_from_conversation(
    session_id: str,
    title: str,
    chart_type: Literal["bar", "line", "pie", "scatter"],
    intent: str,
    conversation_text: str,
) -> VisualSpec:
    """
    Chart draft from explicit conversation context.

    This is Studio pulling context from chat, not chat invoking Studio.
    Numbers still must pass the same extraction pipeline.
    """
    sources = [
        SourceText(
            text=conversation_text[:3000],
            title="Conversation context",
            url=f"session://{session_id}/conversation",
        )
    ]

    extraction = extract_grounded_values(sources)

    if not extraction.grounded:
        return _build_illustrative_spec(session_id, title, chart_type, intent)

    return _build_grounded_spec(
        session_id=session_id,
        title=title,
        chart_type=chart_type,
        sources=sources,
        intent=intent,
    )

    
def _run_search_sync(query: str) -> list[SourceText]:
    """
    Safe wrapper: works whether or not an event loop is already running.
    studio.py endpoints are sync (FastAPI thread pool), so asyncio.run()
    is fine. But this guards against future async endpoint changes.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, _search_and_collect(query))
            return future.result(timeout=30)
    else:
        return asyncio.run(_search_and_collect(query))


async def _search_and_collect(query: str) -> list[SourceText]:
    """
    Reuses paper_search + web_search as plain function calls.
    Returns SourceText list with real URLs for citation.
    """
    from app.services.paper_search import search_openalex_async, search_arxiv_async
    from app.services.web_search import search_web_async

    sources: list[SourceText] = []

    oa_task = search_openalex_async(query, limit=5)
    arxiv_task = search_arxiv_async(query, max_results=3)
    web_task = search_web_async(query, max_results=3)

    results = await asyncio.gather(oa_task, arxiv_task, web_task, return_exceptions=True)

    for result in results:
        if isinstance(result, Exception) or not result:
            continue
        for paper in result:
            text = paper.get("summary", "") or paper.get("text", "")
            if not text:
                continue
            sources.append(SourceText(
                text=text[:2000],
                title=paper.get("title", ""),
                url=paper.get("link", ""),
            ))

    return sources[:8]


def _build_grounded_spec(
    session_id: str,
    title: str,
    chart_type: Literal["bar", "line", "pie", "scatter"],
    sources: list[SourceText],
    intent: str,
) -> VisualSpec:
    """
    Calls the shared extraction function, builds a VisualSpec with
    per-value provenance. Anything ungrounded → unsupported list.
    """
    extraction = extract_grounded_values(sources)

    if not extraction.grounded:
        return _build_illustrative_spec(session_id, title, chart_type, intent)

    categories = [g.label for g in extraction.grounded[:10]]
    values = [g.value for g in extraction.grounded[:10]]
    unit = extraction.grounded[0].unit if extraction.grounded else None

    provenance = []
    for g in extraction.grounded[:10]:
        provenance.append(Provenance(
            kind=ProvenanceKind.GROUNDED,
            source_paper_id=g.source.paper_id,
            source_ref_id=g.source.ref_id,
            source_url=g.source.url,
            source_quote=g.source_quote,
        ))

    series = [ChartSeries(
        label=intent or "Extracted data",
        values=values,
        unit=unit,
        provenance=provenance,
    )]

    payload = ChartPayload(
        chart_type=chart_type,
        categories=categories,
        series=series,
        y_label=unit,
    )

    spec = VisualSpec(
        visual_id=str(uuid.uuid4()),
        session_id=session_id,
        title=title,
        grounding=GroundingSummary(
            level="grounded",
            grounded_count=len(values),
            citations=[
                g.source.ref_id
                for g in extraction.grounded[:10]
                if g.source.ref_id is not None
            ],
        ),
        payload=payload,
    )
    spec.grounding = recompute_grounding(payload)
    return spec


def _build_illustrative_spec(
    session_id: str,
    title: str,
    chart_type: Literal["bar", "line", "pie", "scatter"],
    intent: str,
) -> VisualSpec:
    """
    Returned when nothing can be grounded. Explicitly flagged as ILLUSTRATIVE.
    The renderer will stamp a visible watermark. Never presented as real data.
    """
    payload = ChartPayload(
        chart_type=chart_type,
        categories=["Category A", "Category B", "Category C"],
        series=[ChartSeries(
            label="Placeholder",
            values=[0, 0, 0],
            provenance=[
                Provenance(kind=ProvenanceKind.ILLUSTRATIVE)
                for _ in range(3)
            ],
        )],
    )

    return VisualSpec(
        visual_id=str(uuid.uuid4()),
        session_id=session_id,
        title=title,
        caption=f"Illustrative template — no grounded data found for: {intent}",
        grounding=GroundingSummary(level="illustrative", illustrative_count=3),
        payload=payload,
    )


def revise_spec(spec: VisualSpec, edits: dict) -> VisualSpec:
    """
    Apply user edits to an existing spec. No LLM call.
    If a grounded value's NUMBER is edited, provenance flips to USER_PROVIDED
    (or USER_EDITED if you added it to ProvenanceKind).
    """
    payload = spec.payload
    if not isinstance(payload, ChartPayload):
        return spec

    if "categories" in edits:
        payload.categories = edits["categories"]

    if "series" in edits:
        for i, series_edit in enumerate(edits["series"]):
            if i >= len(payload.series):
                break
            s = payload.series[i]

            if "label" in series_edit:
                s.label = series_edit["label"]

            if "values" in series_edit:
                new_values = series_edit["values"]
                for j, new_val in enumerate(new_values):
                    if j < len(s.values) and j < len(s.provenance):
                        old_val = s.values[j]
                        s.values[j] = new_val
                        if new_val != old_val and s.provenance[j].kind == ProvenanceKind.GROUNDED:
                            s.provenance[j] = Provenance(
                                kind=ProvenanceKind.USER_PROVIDED,
                                note=f"User edited from {old_val}",
                            )

    if "chart_type" in edits:
        payload.chart_type = edits["chart_type"]

    if "x_label" in edits:
        payload.x_label = edits["x_label"]
    if "y_label" in edits:
        payload.y_label = edits["y_label"]

    spec.revision += 1
    spec.payload = payload
    spec.grounding = recompute_grounding(payload)
    return spec