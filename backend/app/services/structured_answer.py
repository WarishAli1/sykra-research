import json
from app.agents.schemas import FollowupAnswer
from app.services.llm_client import _is_rate_limit_error


def _extract_content(msg) -> str:
    return msg.content if hasattr(msg, "content") else str(msg)


def _clean_json_block(text: str) -> str:
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return text.strip()


def get_followup_answer(llm, messages, question: str, context_block: str, fallback_sources: list[str]) -> FollowupAnswer:
    result: FollowupAnswer | None = None

    try:
        result = llm.with_structured_output(FollowupAnswer).invoke(messages, config={"timeout": 20})
        return result
    except Exception as e:
        print(f"[followup] tier1 (structured) failed: {type(e).__name__}: {e}")
        if _is_rate_limit_error(e):
            print("[followup] rate limit detected — short-circuiting further LLM retries")
            return FollowupAnswer(
                answer="The system is currently rate-limited. Please try again in a moment.",
                sources_used=fallback_sources,
                grounded=False,
            )

    try:
        raw = llm.invoke(messages, config={"timeout": 20})
        clean = _clean_json_block(_extract_content(raw))
        data = json.loads(clean)
        return FollowupAnswer(**data)
    except Exception as e:
        print(f"[followup] tier2 (json parse) failed: {type(e).__name__}: {e}")

    try:
        raw = llm.invoke(
            f"Answer the question using only the excerpts below. If they don't cover it, say so honestly.\n\n"
            f"Question: {question}\n\nExcerpts:\n{context_block}\n\nAnswer:",
            config={"timeout": 20}
        )
        answer_text = _extract_content(raw)
        return FollowupAnswer(answer=answer_text, sources_used=fallback_sources, grounded=True)
    except Exception as e:
        print(f"[followup] tier3 (plain text) failed: {type(e).__name__}: {e}")

    print("[followup] ALL TIERS FAILED — check Groq API key validity / rate limits above")
    return FollowupAnswer(
        answer="I could not process this question right now due to a processing error. This may be a temporary rate limit — please try again shortly.",
        sources_used=[],
        grounded=False,
    )
