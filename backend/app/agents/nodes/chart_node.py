import os
import uuid

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import seaborn as sns

from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field
from typing import Literal

from app.agents.state import AgentState
from app.services.llm_client import get_llm
from app.config import settings


EXPORT_DIR = "exports"
os.makedirs(EXPORT_DIR, exist_ok=True)


_VISUAL_INTENT_WORDS = (
    "graph",
    "chart",
    "plot",
    "diagram",
    "visualiz",
    "visualise",
    "picture",
    "image",
    "figure",
    "compare visually",
    "show me a",
)


def _has_visual_intent(query: str) -> bool:
    q = query.lower()
    return any(w in q for w in _VISUAL_INTENT_WORDS)


def _plan_wants_chart(state: AgentState) -> bool:
    plan = state.get("report_plan") or {}
    needs = {str(n).lower() for n in plan.get("information_needs", [])}
    return "visualization" in needs or "chart" in needs or "graph" in needs


class ChartSeries(BaseModel):
    label: str = ""
    x: list[str] = Field(default_factory=list)
    y: list[float] = Field(default_factory=list)


class ChartSpec(BaseModel):
    has_chartable_data: bool = Field(
        description=(
            "True only if the papers contain real, explicitly stated comparable numeric data "
            "relevant to the query."
        )
    )
    chart_type: Literal["bar", "line", "scatter"] = "bar"
    title: str = ""
    x_label: str = ""
    y_label: str = ""
    series: list[ChartSeries] = Field(default_factory=list)


_PLACEHOLDER_TITLE_MARKERS = (
    "placeholder",
    "illustrative",
    "example",
    "sample data",
    "dummy",
)


def _looks_numeric(v) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def _looks_like_year(v) -> bool:
    try:
        fv = float(v)
        return 1900 <= fv <= 2100
    except (TypeError, ValueError):
        return False


def _looks_like_placeholder(spec: ChartSpec) -> bool:
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
            if spec.chart_type == "line" and all(_looks_like_year(v) for v in s.x):
                continue

            label = (s.label or "").lower()
            if spec.chart_type == "line" and any(k in label for k in ("year", "trend", "citation", "published")):
                continue

            return True

    return False


_CHART_SPEC_PROMPT = """You are extracting real, citable numeric data from research papers to build ONE chart.

USER QUESTION: {query}

PAPERS:
{paper_block}

Extract ONLY numbers explicitly stated above.
NEVER estimate or invent a number.

Set has_chartable_data=false if no real comparable numeric data exists.

If has_chartable_data=true:
- chart_type: bar for categorical comparisons, line for trends over years, scatter for correlations
- title, x_label, y_label: short descriptive labels
- series: one or more {{label, x, y}} groups

Return a ChartSpec JSON object.
"""


def _generate_chart_spec(
    query: str,
    papers: list[dict],
    summaries: dict,
    allow_fallback_metrics: bool = False,
) -> ChartSpec | None:
    if not papers:
        return None

    paper_block = "\n\n".join(
        [
            f"[{i}] {p.get('title', '')} "
            f"(published: {p.get('published', 'unknown')}, citations: {p.get('citation_count', 0)}): "
            f"{summaries.get(str(i), {}).get('key_contribution', '')} "
            f"{summaries.get(str(i), {}).get('findings', '')}"
            + (
                f" | Key metrics: {'; '.join(summaries.get(str(i), {}).get('key_metrics', []))}"
                if summaries.get(str(i), {}).get("key_metrics")
                else ""
            )
            for i, p in enumerate(papers)
        ]
    )

    prompt = _CHART_SPEC_PROMPT.format(query=query, paper_block=paper_block)

    if allow_fallback_metrics:
        prompt += (
            "\n\nNo strong candidate numeric data was found on the first pass. "
            "If no in-text metrics are usable, it is acceptable to chart publication year or citation count per paper."
        )

    llm = get_llm(temperature=0, task="default")

    try:
        spec = llm.with_structured_output(ChartSpec).invoke(
            [
                SystemMessage(content="Respond with ONLY a function call to ChartSpec."),
                HumanMessage(content=prompt),
            ],
            config={"timeout": settings.REPORT_CHART_TIMEOUT},
        )

        if isinstance(spec, dict):
            spec = ChartSpec.model_validate(spec)

        return spec

    except Exception as e:
        print(f"[chart_node] chart_spec generation failed: {type(e).__name__}: {e}")
        return None


def _render_chart(spec: ChartSpec) -> str | None:
    try:
        if _looks_like_placeholder(spec):
            print("[chart_node] rejecting chart_spec: placeholder-like")
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
        print(f"[chart_node] render failed: {type(e).__name__}: {e}")
        return None


def chart_node(state: AgentState) -> AgentState:
    query = state.get("query", "")
    response_mode = state.get("response_mode", "normal")
    answer = state.get("final_answer", "")

    print(f"[chart_node] mode={response_mode}, query={query[:80]}...")

    if response_mode not in ("researched", "graph_research"):
        print("[chart_node] skipping: normal mode latency budget")
        return {
            "chart_spec_raw": None,
            "chart_url": None,
        }

    if not (_has_visual_intent(query) or _plan_wants_chart(state)):
        print("[chart_node] skipping: no visual intent")
        return {
            "chart_spec_raw": None,
            "chart_url": None,
        }

    papers = state.get("ranked_papers", [])
    summaries = state.get("summaries", {})

    print(f"[chart_node] visual intent detected, generating chart_spec from {len(papers)} papers...")

    spec = _generate_chart_spec(query, papers, summaries)

    if spec is None or _looks_like_placeholder(spec):
        print("[chart_node] first attempt empty/placeholder-like, retrying with fallback metrics")
        spec = _generate_chart_spec(query, papers, summaries, allow_fallback_metrics=True) or spec

    if spec is None:
        print("[chart_node] chart_spec generation failed")
        return {
            "chart_spec_raw": None,
            "chart_url": None,
        }

    raw_spec = spec.model_dump_json()
    chart_path = _render_chart(spec)

    if not chart_path:
        return {
            "chart_spec_raw": raw_spec,
            "chart_url": None,
        }

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