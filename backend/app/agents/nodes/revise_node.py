import re
from langchain_core.messages import SystemMessage, HumanMessage
from app.agents.state import AgentState
from app.services.llm_client import get_llm
from app.config import settings


QUALITY_RULES = """
- Do NOT remove or alter existing citation markers like [1], [2], or [paper_id=N].
- Do NOT invent new citations. Only cite paper_ids present in AVAILABLE SOURCES.
- If the gap exists because the literature does not cover it, say so explicitly
  with a clear limitation sentence rather than filling it with speculation.
- Preserve the existing markdown structure (headings, tables, bullet lists).
- Do NOT repeat facts, numbers, or arguments already present elsewhere in the report.
"""

REVISE_TIMEOUT = 30


def _extract_missing_module_titles(instruction: str) -> list[str]:
    """Pull module titles from the revision instruction so we can
    generate ONLY those sections instead of rewriting everything.

    critique_node joins missing_modules with '; ' (see
    'Cover or explicitly explain missing modules: ' + '; '.join(...)),
    so this must split on ';' — splitting on ',' silently failed
    whenever more than one module was missing (the common case),
    causing a fallthrough to the expensive full-rewrite path below.
    """
    titles = []
    m = re.search(r"missing modules?:\s*(.+?)(?:\.\s|\.$|$)", instruction, re.IGNORECASE)
    if m:
        for part in m.group(1).split(";"):
            t = part.strip().strip(".")
            if t and len(t) > 3:
                titles.append(t)
    return titles


def revise_node(state: AgentState) -> AgentState:
    if not state.get("needs_revision"):
        return {"needs_revision": False}

    draft = state.get("final_answer", "")
    instruction = state.get("revision_instruction", "")

    if not draft or not instruction:
        return {"needs_revision": False}

    ref_marker = "\n\n---\n\n**References**"
    if ref_marker in draft:
        body, refs_block = draft.split(ref_marker, 1)
        refs_block = ref_marker + refs_block
    else:
        body = draft
        refs_block = ""

    missing_titles = _extract_missing_module_titles(instruction)
    llm = get_llm(temperature=0, task="strong")

    if missing_titles:
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
{chr(10).join(f'- {t}' for t in missing_titles)}

RULES:
- Start each section with a ## heading matching its title.
- Keep each section to 150-300 words.
- Do NOT rewrite or summarize the existing report.
{QUALITY_RULES}
Return markdown only. No JSON.
""".strip()

        try:
            response = llm.invoke(
                [
                    SystemMessage(content="You add missing sections to research reports. Return markdown only."),
                    HumanMessage(content=sections_prompt),
                ],
                config={"timeout": REVISE_TIMEOUT},
            )
            new_sections = response.content.strip()

            if new_sections and len(new_sections) > 100:
                revised = body.rstrip() + "\n\n" + new_sections + refs_block
                print(f"[revise_node] targeted path succeeded ({len(missing_titles)} sections)")
                return {
                    "final_answer": revised,
                    "needs_revision": False,
                }
            print("[revise_node] targeted path returned too little content, falling back")
        except Exception as e:
            print(f"[revise_node] targeted path failed: {type(e).__name__}: {e}, falling back")

    prompt = f"""Revise this answer to fix ONE specific gap.

GAP TO FIX:
{instruction}

CURRENT ANSWER:
{body}

Rules:
- Make the minimal edit needed. Add 2-4 sentences or one short paragraph,
  or a full section only if the gap genuinely requires one.
- Do NOT rewrite sections that are already fine.
{QUALITY_RULES}
Return the full revised answer body only.
"""

    try:
        response = llm.invoke(
            [
                SystemMessage(content="You make minimal, targeted edits to research answers. Return the full revised text only."),
                HumanMessage(content=prompt),
            ],
            config={"timeout": REVISE_TIMEOUT},
        )
        revised = response.content.strip()
        if ref_marker in revised:
            revised = revised.split(ref_marker, 1)[0].rstrip()

        if len(revised) < max(200, int(len(body) * 0.25)):
            print("[revise_node] fallback path returned suspiciously short output, keeping original")
            return {"needs_revision": False}

        print("[revise_node] fallback path used")
        return {
            "final_answer": revised + refs_block,
            "needs_revision": False,
        }
    except Exception as e:
        print(f"[revise_node] fallback path failed, keeping original: {type(e).__name__}: {e}")
        return {"needs_revision": False}