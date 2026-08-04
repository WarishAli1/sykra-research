from langchain_core.messages import SystemMessage, HumanMessage
from app.agents.state import AgentState
from app.services.llm_client import get_llm
from app.utils.text_sanitizer import sanitize_for_web

_PREVIEW_SYSTEM = """
You are a fast research assistant.
Write a short provisional direct answer using ONLY the retrieved paper evidence below.
Rules:
- 2 to 5 sentences only.
- Do not write a full report.
- Do not invent citations.
- Use inline citations as [paper_id=N] with ASCII square brackets only.
- If evidence is weak, say so briefly.
- Be direct and concrete.
- Never use the $ symbol for currency. Write "USD 48/MWh" instead of "$48/MWh".
"""


def _build_preview_paper_block(papers: list[dict]) -> str:
    parts = []
    for i, p in enumerate(papers[:3]):
        title = p.get("title", "")
        abstract = (p.get("summary") or p.get("text") or "")[:700]
        parts.append(
            f"[paper_id={i}] Title: {title}\n"
            f"Abstract: {abstract}"
        )
    return "\n\n".join(parts)


def _fallback_preview(papers: list[dict]) -> str:
    if not papers:
        return "I found no strong evidence yet. Generating a fuller answer now."
    titles = [p.get("title", "") for p in papers[:2] if p.get("title")]
    if titles:
        return (
            "Initial evidence suggests the answer is emerging from the top retrieved papers. "
            f"Relevant work includes: {', '.join(titles)}. "
            "A full synthesized answer is being generated now."
        )
    return "A quick answer is being prepared from the top retrieved papers. Full synthesis is continuing."


def preview_node(state: AgentState) -> AgentState:
    papers = state.get("ranked_papers", [])
    if not papers:
        return {
            "preview_answer": "",
            "preview_streamed": False,
        }

    query = state.get("query", "")
    paper_block = _build_preview_paper_block(papers)

    prompt = f"""
USER QUERY:
{query}

TOP RETRIEVED PAPERS:
{paper_block}

Write the provisional direct answer now.
""".strip()

    try:
        llm = get_llm(temperature=0, task="fast")
        response = llm.invoke(
            [
                SystemMessage(content=_PREVIEW_SYSTEM.strip()),
                HumanMessage(content=prompt),
            ],
            config={"timeout": 8},
        )
        preview = (response.content or "").strip()
        if len(preview) < 20:
            preview = _fallback_preview(papers)
    except Exception as e:
        print(f"[preview_node] preview generation failed: {type(e).__name__}: {e}")
        preview = _fallback_preview(papers)

    return {
        "preview_answer": sanitize_for_web(preview),
        "preview_streamed": False,
    }