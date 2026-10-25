import re

from langchain_core.messages import SystemMessage, HumanMessage

_CITE_RE = re.compile(r"\[(?:paper_id=)?\d+\]")
_MAX_CLASSIFY_WORDS = 60

_SYSTEM = (
    "You classify one new chat message against the conversation so far. "
    "Return ONLY a valid JSON object. No markdown. No explanations."
)

_PROMPT = """CONVERSATION SO FAR:
{history}

NEW MESSAGE:
{query}

Return JSON with three fields.

1. intent
   "followup": the message cannot be understood without the conversation
   (pronouns like it/they/this, "the second method", "explain more", "why?",
   "compare them", "give that as a table", "what about limitations?").
   "independent": understandable on its own, or a different topic.

2. standalone_query  (used ONLY to search papers)
   - If independent: the NEW MESSAGE unchanged.
   - If followup: a SHORT search-style question, maximum 12 words.
   - Use ONLY entity and topic names that already appear in the conversation.
   - Keep the question type (limitations, comparison, explanation, example, ...).
   - NEVER add definitions, descriptions, applications, or sub-topics.
     Do not write things like "including causes, symptoms", or "the technique used to ...".
   - Do NOT put presentation words (table, shorter, simpler, bullets, step by step)
     in standalone_query.
   - Examples:
       conversation about Grad-CAM, message "what are its limitations?"
         -> "limitations of Grad-CAM"
       conversation about LIME and SHAP, message "explain the second method in more detail"
         -> "SHAP explained in detail"
       conversation about pneumonia, message "give that as a table"
         -> "pneumonia"

3. output_instruction
   Any presentation request in the NEW MESSAGE (for example "present as a markdown
   table", "shorter", "simpler language", "bullet points", "step by step").
   Empty string if there is none.

Return JSON: {{"intent": "followup" | "independent", "standalone_query": "...", "output_instruction": "..."}}
"""


def _clip(text: str, limit: int) -> str:
    text = _CITE_RE.sub("", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + " ..."


def format_history(history: list[dict], last_n: int = 4, per_msg: int = 500) -> str:
    lines = []
    for m in (history or [])[-last_n:]:
        who = "User" if m.get("role") == "user" else "Assistant"
        lines.append(f"{who}: {_clip(m.get('content', ''), per_msg)}")
    return "\n".join(lines)


def needs_classification(query: str, history: list[dict]) -> bool:
    q = (query or "").strip()
    if not history or not q:
        return False
    return len(q.split()) <= _MAX_CLASSIFY_WORDS


def classify_turn(query: str, history: list[dict], llm, timeout: int = 4) -> dict:
    """
    Returns {"intent": "independent"|"followup", "standalone_query": str, "output_instruction": str}.
    Never raises. Any failure falls back to an independent question.
    """
    result = {"intent": "independent", "standalone_query": query, "output_instruction": ""}

    if not needs_classification(query, history):
        return result

    try:
        raw = llm.invoke_json_mode(
            [
                SystemMessage(content=_SYSTEM),
                HumanMessage(
                    content=_PROMPT.format(
                        history=format_history(history),
                        query=query,
                    )
                ),
            ],
            config={"timeout": timeout},
        )
    except Exception as e:
        print(f"[conversation] classify failed: {type(e).__name__}: {e}")
        return result

    if not isinstance(raw, dict):
        return result

    intent = str(raw.get("intent") or "").strip().lower()
    standalone = str(raw.get("standalone_query") or "").strip()
    instruction = str(raw.get("output_instruction") or "").strip()[:160]

    if instruction.lower() in ("none", "null", "n/a", "no"):
        instruction = ""

    result["output_instruction"] = instruction

    if intent == "followup" and 3 <= len(standalone) <= 160:
        result["intent"] = "followup"
        result["standalone_query"] = standalone

    return result


def conversation_block(state: dict, max_assistant_chars: int = 1200) -> str:
    """Context for the writer. Only emitted for follow-ups."""
    if not state.get("is_followup"):
        return ""

    history = state.get("conversation_history") or []
    if not history:
        return ""

    lines = []
    for m in history[-2:]:
        is_user = m.get("role") == "user"
        lines.append(
            f"{'User' if is_user else 'Assistant'}: "
            f"{_clip(m.get('content', ''), 400 if is_user else max_assistant_chars)}"
        )

    original = state.get("original_query") or ""

    return (
        "CONVERSATION CONTEXT (the user is following up on this. Use it ONLY to understand "
        "what they mean. It is not evidence: cite and state facts only from the allowed sources):\n"
        + "\n".join(lines)
        + (f"\nUSER'S CURRENT MESSAGE, AS TYPED: {original}" if original else "")
    )


def format_override(state: dict) -> str:
    """Presentation request (table, shorter, ...) that must beat the default answer template."""
    instruction = (state.get("output_instruction") or "").strip()
    if not instruction:
        return ""
    return (
        f"PRESENTATION REQUEST FROM THE USER: {instruction}.\n"
        "Follow it exactly. Where it conflicts with the default section labels or structure "
        "below, the presentation request wins (for example, use a markdown table if a table "
        "was requested). Every row or bullet that states a fact must still carry its "
        "[paper_id=N] citation. If the sources do not cover a cell or point, write "
        "'not covered by the sources' instead of filling it in."
    )