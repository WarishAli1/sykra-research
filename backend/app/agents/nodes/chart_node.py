import json
import os
import re
import uuid

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field
from typing import Literal, Optional

from app.agents.state import AgentState
from app.services.llm_client import get_llm

EXPORT_DIR = "exports"
os.makedirs(EXPORT_DIR, exist_ok=True)

_VISUAL_INTENT_WORDS = (
    "graph", "chart", "plot", "diagram", "visualiz", "visualise",
    "picture", "image", "figure", "compare visually", "show me a",
)


def _has_visual_intent(query: str) -> bool:
    q = query.lower()
    return any(w in q for w in _VISUAL_INTENT_WORDS)


class ChartSeries(BaseModel):
    label: str = ""
    x: list[str] = Field(default_factory=list)
    y: list[float] = Field(default_factory=list)


class ChartSpec(BaseModel):
    """A chart to render from real, paper-reported numeric data only."""
    has_chartable_data: bool = Field(
        description="True only if the papers contain real, explicitly stated "
                    "comparable numeric data relevant to the query. False if "
                    "no such data exists — do NOT fabricate a chart in that case."
    )
    chart_type: Literal["bar", "line", "scatter"] = "bar"
    title: str = ""
    x_label: str = ""
    y_label: str = ""
    series: list[ChartSeries] = Field(default_factory=list)


_PLACEHOLDER_TITLE_MARKERS = ("placeholder", "illustrative", "example", "sample data", "dummy")


def _looks_like_placeholder(spec: ChartSpec) -> bool:
    """Defense-in-depth: reject specs that look fabricated rather than
    extracted from real paper data, even if the LLM ignored instructions.
    Catches the common failure mode of emitting normalized/generic axes
    (e.g. x/y in [0,1] with no real category labels) instead of real figures."""
    if not spec.has_chartable_data:
        return True
    title = (spec.title or "").lower()
    if any(marker in title for marker in _PLACEHOLDER_TITLE_MARKERS):
        return True
    if not spec.series:
        return True
    for s in spec.series:
        if not s.x or not s.y:
            continue
        if all(_looks_numeric(v) for v in s.x):
            return True
    return False


def _looks_numeric(v) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


_CHART_SPEC_PROMPT = """You are extracting real, citable numeric data from research papers to build ONE chart that helps answer the user's question.

USER QUESTION: {query}

PAPERS (title + key findings/contribution + "Key metrics" when the paper
states exact numbers — this is your primary source of chartable data):
{paper_block}

Extract ONLY numbers that are explicitly stated above, especially in the
"Key metrics" field of each paper (e.g. reported accuracy/F1/BLEU/top-1
scores or deltas, publication years, parameter counts, latency, dataset
sizes). NEVER estimate, infer, or invent a number. Approximate ranges
explicitly stated in the source (e.g. "2-4%") are fine to use — pick a
representative value or the midpoint, but only when the source itself
gave a number.

Set has_chartable_data=false if the papers do not contain real comparable
numeric data relevant to the question — this is the common case for surveys
and qualitative papers, and is perfectly fine. A chart is only useful when
grounded in real reported figures.

If has_chartable_data=true, fill in:
- chart_type: "bar" for categorical comparisons, "line" for trends over time/years, "scatter" for correlations
- title, x_label, y_label: short descriptive labels
- series: one or more {{label, x, y}} groups, where x are real category/model/paper names (NOT generic numbers) and y are the real numeric values found in the text

Return a ChartSpec JSON object matching the schema exactly."""


def _generate_chart_spec(query: str, papers: list[dict], summaries: dict, allow_fallback_metrics: bool = False) -> ChartSpec | None:
    """Small, dedicated LLM call to extract chart data — separate from the
    big researched-mode report call so a token-limit failure on the report
    doesn't also prevent the chart from being generated.

    allow_fallback_metrics: on retry, explicitly permits using publication
    year and citation count (always present on every paper dict, unlike
    key_metrics which depends on the abstract stating exact figures) as
    legitimate chartable axes when no other numeric data was extracted."""
    if not papers:
        return None

    paper_block = "\n\n".join([
        f"[{i}] {p.get('title', '')} (published: {p.get('published', 'unknown')}, "
        f"citations: {p.get('citation_count', 0)}): "
        f"{summaries.get(str(i), {}).get('key_contribution', '')} "
        f"{summaries.get(str(i), {}).get('findings', '')}"
        + (
            f" | Key metrics: {'; '.join(summaries.get(str(i), {}).get('key_metrics', []))}"
            if summaries.get(str(i), {}).get('key_metrics')
            else ""
        )
        for i, p in enumerate(papers)
    ])

    prompt = _CHART_SPEC_PROMPT.format(query=query, paper_block=paper_block)
    if allow_fallback_metrics:
        prompt += (
            "\n\nNo strong candidate numeric data was found on the first pass. "
            "If no in-text metrics are usable, it is acceptable to chart "
            "publication year or citation count per paper (both given above) "
            "as a real, non-fabricated comparison — e.g. a bar chart of "
            "citation counts across the retrieved papers. Only set "
            "has_chartable_data=false if even this is not meaningful for the "
            "question asked."
        )

    llm = get_llm(temperature=0)
    try:
        spec = llm.with_structured_output(ChartSpec).invoke(
            [
                SystemMessage(content="Respond with ONLY a function call to ChartSpec. No text before or after."),
                HumanMessage(content=prompt),
            ],
            config={"timeout": 30},
        )
        if isinstance(spec, dict):
            spec = ChartSpec.model_validate(spec)
        return spec
    except Exception as e:
        print(f"[chart_node] chart_spec generation failed: {type(e).__name__}: {e}")
        return None


def _render_chart(spec: ChartSpec) -> str | None:
    """Render spec with seaborn, return the saved PNG path, or None on failure."""
    try:
        if _looks_like_placeholder(spec):
            print("[chart_node] rejecting chart_spec: no real chartable data / looks like placeholder")
            return None

        sns.set_theme(style="whitegrid")
        fig, ax = plt.subplots(figsize=(7, 4.2), dpi=150)

        for s in spec.series:
            xs, ys = s.x, s.y
            if not xs or not ys or len(xs) != len(ys):
                continue

            if spec.chart_type == "line":
                sns.lineplot(x=xs, y=ys, marker="o", label=s.label or None, ax=ax)
            elif spec.chart_type == "scatter":
                sns.scatterplot(x=xs, y=ys, label=s.label or None, ax=ax)
            else:
                sns.barplot(x=xs, y=ys, ax=ax, label=s.label or None)

        ax.set_title(spec.title)
        ax.set_xlabel(spec.x_label)
        ax.set_ylabel(spec.y_label)
        if any(s.label for s in spec.series):
            ax.legend()
        plt.xticks(rotation=25, ha="right")
        fig.tight_layout()

        filename = f"chart-{uuid.uuid4().hex[:10]}.png"
        path = os.path.join(EXPORT_DIR, filename)
        fig.savefig(path)
        plt.close(fig)
        return path
    except Exception as e:
        print(f"[chart_node] render failed: {e}")
        return None


def chart_node(state: AgentState) -> AgentState:
    query = state.get("query", "")
    response_mode = state.get("response_mode", "normal")
    answer = state.get("final_answer", "")

    print(f"[chart_node] mode={response_mode}, query={query[:80]}...")

    if response_mode not in ("researched", "graph_research"):
        print(f"[chart_node] skipping: wrong mode {response_mode}")
        return {"chart_spec_raw": None, "chart_url": None}

    if not _has_visual_intent(query):
        print(f"[chart_node] skipping: no visual intent in query")
        return {"chart_spec_raw": None, "chart_url": None}

    papers = state.get("ranked_papers", [])
    summaries = state.get("summaries", {})

    print(f"[chart_node] visual intent detected, generating chart_spec from {len(papers)} papers...")
    spec = _generate_chart_spec(query, papers, summaries)

    if spec is None or _looks_like_placeholder(spec):
        print("[chart_node] first attempt empty/placeholder-like, retrying with fallback-metric nudge")
        spec = _generate_chart_spec(query, papers, summaries, allow_fallback_metrics=True) or spec

    if spec is None:
        print(f"[chart_node] chart_spec generation failed or returned nothing")
        return {"chart_spec_raw": None, "chart_url": None}

    raw_spec = spec.model_dump_json()
    chart_path = _render_chart(spec)
    if not chart_path:
        return {"chart_spec_raw": raw_spec, "chart_url": None}

    chart_url = f"/{chart_path}"
    alt_text = spec.title or "Generated chart"

    cleaned_answer = answer
    ref_marker = "\n\n---\n\n**References**"
    if ref_marker in cleaned_answer:
        idx = cleaned_answer.index(ref_marker)
        cleaned_answer = cleaned_answer[:idx] + f"\n\n![{alt_text}]({chart_url})" + cleaned_answer[idx:]
    else:
        cleaned_answer += f"\n\n![{alt_text}]({chart_url})"

    return {
        "final_answer": cleaned_answer,
        "chart_spec_raw": raw_spec,
        "chart_url": chart_url,
    }