import time
import json
import re
from langchain_core.messages import HumanMessage
from pydantic import ValidationError
from langchain_groq import ChatGroq
from langchain_cerebras import ChatCerebras
from app.config import settings


def _extract_json(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group(0) if match else text

def _is_rate_limit_error(e: Exception) -> bool:
    msg = str(e).lower()
    return ("rate_limit" in msg or "429" in msg or "413" in msg or
            "quota" in msg or "capacity" in msg or "too many requests" in msg)


_call_counts = {"groq_key1": 0, "groq_key2": 0, "cerebras_key1": 0, "cerebras_key2": 0}


def _build_providers(temperature: float, preferred_order: list[str] | None = None):
    all_providers = {}

    if settings.GROQ_API_KEY:
        all_providers["groq_key1"] = lambda: ChatGroq(
            api_key=settings.GROQ_API_KEY, model="openai/gpt-oss-120b",
            temperature=temperature, request_timeout=30
        )
    if settings.GROQ_API_KEY_2:
        all_providers["groq_key2"] = lambda: ChatGroq(
            api_key=settings.GROQ_API_KEY_2, model="openai/gpt-oss-120b",
            temperature=temperature, request_timeout=30
        )
    if settings.CEREBRAS_API_KEY:
        all_providers["cerebras_key1"] = lambda: ChatCerebras(
            api_key=settings.CEREBRAS_API_KEY, model="gpt-oss-120b", temperature=temperature
        )
    if settings.CEREBRAS_API_KEY_2:
        all_providers["cerebras_key2"] = lambda: ChatCerebras(
            api_key=settings.CEREBRAS_API_KEY_2, model="gpt-oss-120b", temperature=temperature
        )

    order = preferred_order or list(all_providers.keys())
    return [(name, all_providers[name]) for name in order if name in all_providers]


class _StructuredFailoverRunner:
    def __init__(self, temperature, schema, preferred_order=None):
        self.temperature = temperature
        self.schema = schema
        self.preferred_order = preferred_order

    def invoke(self, prompt, **kwargs):
        last_exc = None
        providers = _build_providers(self.temperature, self.preferred_order)
        for attempt, (name, build) in enumerate(providers):
            model = build()
            try:
                result = model.with_structured_output(self.schema).invoke(prompt, **kwargs)
                _call_counts[name] += 1
                return result
            except Exception as e:
                print(f"[llm_client] {name} structured failed: {type(e).__name__}: {e}")
                last_exc = e

            try:
                schema_json = self.schema.model_json_schema()
                json_prompt = list(prompt) + [HumanMessage(content=(
                    f"Respond with ONLY a JSON object matching this schema, "
                    f"no markdown fences, no preamble:\n{json.dumps(schema_json)}"
                ))]
                raw = model.invoke(json_prompt, **kwargs)
                parsed = json.loads(_extract_json(raw.content))
                result = self.schema.model_validate(parsed)
                _call_counts[name] += 1
                return result
            except Exception as e2:
                print(f"[llm_client] {name} JSON fallback failed: {type(e2).__name__}: {e2}")
                last_exc = e2

            if _is_rate_limit_error(last_exc):
                wait = min(2 ** (attempt + 1), 10)
                print(f"[llm_client] Rate limited on {name}, waiting {wait}s...")
                time.sleep(wait)
            else:
                time.sleep(0.5)
        raise last_exc or RuntimeError("All LLM providers exhausted")


class FailoverLLM:
    def __init__(self, temperature: float = 0.2, preferred_order=None):
        self.temperature = temperature
        self.preferred_order = preferred_order

    def with_structured_output(self, schema):
        return _StructuredFailoverRunner(self.temperature, schema, self.preferred_order)

    def invoke(self, prompt, **kwargs):
        last_exc = None
        providers = _build_providers(self.temperature, self.preferred_order)
        for attempt, (name, build) in enumerate(providers):
            try:
                result = build().invoke(prompt, **kwargs)
                _call_counts[name] += 1
                return result
            except Exception as e:
                print(f"[llm_client] {name} failed: {type(e).__name__}: {e}")
                last_exc = e
                if _is_rate_limit_error(e):
                    wait = min(2 ** (attempt + 1), 10)
                    print(f"[llm_client] Rate limited on {name}, waiting {wait}s...")
                    time.sleep(wait)
                else:
                    time.sleep(0.5)
                continue
        raise last_exc or RuntimeError("All LLM providers exhausted")


ORDER_MAP = {
    "light": ["cerebras_key1", "cerebras_key2", "groq_key1", "groq_key2"],
    "default": ["groq_key1", "groq_key2", "cerebras_key1", "cerebras_key2"],
}


def get_llm(temperature: float = 0.2, task: str = "default"):
    return FailoverLLM(temperature=temperature, preferred_order=ORDER_MAP.get(task, ORDER_MAP["default"]))


def get_provider_usage() -> dict:
    return dict(_call_counts)
