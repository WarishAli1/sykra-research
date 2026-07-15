import json
from typing import Callable, TypeVar
from pydantic import BaseModel

from app.agents.schemas import FollowupAnswer
from app.services.llm_client import _is_rate_limit_error

T = TypeVar("T", bound=BaseModel)


def _extract_content(msg) -> str:
    return msg.content if hasattr(msg, "content") else str(msg)


def _clean_json_block(text: str) -> str:
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return text.strip()


def get_structured_with_fallback(llm, messages, schema: type[T], fallback_factory: Callable[[], T]) -> T:
    try:
        return llm.with_structured_output(schema).invoke(messages, config={"timeout": 20})
    except Exception as e:
        if _is_rate_limit_error(e):
            print(f"[structured_answer] rate limited — skipping retries")
            return fallback_factory()
        print(f"[structured_answer] tier1 (structured) failed: {type(e).__name__}: {e}")

    try:
        raw = llm.invoke(messages, config={"timeout": 20})
        clean = _clean_json_block(_extract_content(raw))
        data = json.loads(clean)
        return schema(**data)
    except Exception as e:
        print(f"[structured_answer] tier2 (json parse) failed: {type(e).__name__}: {e}")

    print("[structured_answer] all tiers failed, using default fallback")
    return fallback_factory()


def get_followup_answer(llm, messages, question: str, context_block: str, fallback_sources: list[str]) -> FollowupAnswer:
    try:
        return llm.with_structured_output(FollowupAnswer).invoke(messages, config={"timeout": 20})
    except Exception as e:
        if _is_rate_limit_error(e):
            print("[followup] rate limited — short-circuiting")
            return FollowupAnswer(
                answer="The system is currently rate-limited. Please try again in a moment.",
                sources_used=fallback_sources,
                grounded=False,
            )
        print(f"[followup] tier1 (structured) failed: {type(e).__name__}: {e}")

    try:
        raw = llm.invoke(messages, config={"timeout": 20})
        clean = _clean_json_block(_extract_content(raw))
        data = json.loads(clean)
        return FollowupAnswer(**data)
    except Exception as e:
        print(f"[followup] tier2 (json parse) failed: {type(e).__name__}: {e}")

    try:
        raw = llm.invoke(
            f"Answer the question using only the excerpts below. If they don't cover it, answer ONLY with: 'NOT_GROUNDED'.\n\n"
            f"Question: {question}\n\nExcerpts:\n{context_block}\n\nAnswer:",
            config={"timeout": 20}
        )
        answer_text = _extract_content(raw).strip()
        grounded = not answer_text.upper().startswith("NOT_GROUNDED")
        if not grounded:
            answer_text = "The uploaded document does not contain enough information to answer this question."
        return FollowupAnswer(answer=answer_text, sources_used=fallback_sources, grounded=grounded)
    except Exception as e:
        print(f"[followup] tier3 (plain text) failed: {type(e).__name__}: {e}")

    print("[followup] ALL TIERS FAILED")
    return FollowupAnswer(
        answer="I could not process this question right now due to a processing error.",
        sources_used=[],
        grounded=False,
    )
