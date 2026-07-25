import time
import json
import re
from langchain_core.messages import HumanMessage, SystemMessage
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

_client_cache: dict[tuple[str, float], object] = {}

_CLIENT_FACTORIES = {
    "groq_key1": lambda temperature: ChatGroq(
        api_key=settings.GROQ_API_KEY, model="openai/gpt-oss-120b",
        temperature=temperature, request_timeout=30
    ) if settings.GROQ_API_KEY else None,
    "groq_key2": lambda temperature: ChatGroq(
        api_key=settings.GROQ_API_KEY_2, model="openai/gpt-oss-120b",
        temperature=temperature, request_timeout=30
    ) if settings.GROQ_API_KEY_2 else None,
    "cerebras_key1": lambda temperature: ChatCerebras(
        api_key=settings.CEREBRAS_API_KEY, model="gpt-oss-120b", temperature=temperature
    ) if settings.CEREBRAS_API_KEY else None,
    "cerebras_key2": lambda temperature: ChatCerebras(
        api_key=settings.CEREBRAS_API_KEY_2, model="gpt-oss-120b", temperature=temperature
    ) if settings.CEREBRAS_API_KEY_2 else None,
}


def _get_client(name: str, temperature: float):
    key = (name, temperature)
    client = _client_cache.get(key)
    if client is not None:
        return client
    factory = _CLIENT_FACTORIES.get(name)
    if factory is None:
        return None
    client = factory(temperature)
    if client is not None:
        _client_cache[key] = client
    return client


def _available_providers(preferred_order: list[str] | None) -> list[str]:
    order = preferred_order or list(_CLIENT_FACTORIES.keys())
    configured = {
        "groq_key1": bool(settings.GROQ_API_KEY),
        "groq_key2": bool(settings.GROQ_API_KEY_2),
        "cerebras_key1": bool(settings.CEREBRAS_API_KEY),
        "cerebras_key2": bool(settings.CEREBRAS_API_KEY_2),
    }
    return [name for name in order if configured.get(name)]


class _StructuredFailoverRunner:
    def __init__(self, temperature, schema, preferred_order=None):
        self.temperature = temperature
        self.schema = schema
        self.preferred_order = preferred_order

    def invoke(self, prompt, **kwargs):
        last_exc = None
        providers = _available_providers(self.preferred_order)

        for attempt, name in enumerate(providers):
            model = _get_client(name, self.temperature)
            if model is None:
                continue
            try:
                result = model.with_structured_output(self.schema).invoke(prompt, **kwargs)
                _call_counts[name] += 1
                return result
            except Exception as e:
                print(f"[llm_client] {name} structured failed: {type(e).__name__}: {e}")
                last_exc = e
                if _is_rate_limit_error(e):
                    wait = min(2 ** attempt, 4)
                    time.sleep(wait)

        for attempt, name in enumerate(providers):
            model = _get_client(name, self.temperature)
            if model is None:
                continue
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
                if _is_rate_limit_error(e2):
                    wait = min(2 ** attempt, 4)
                    time.sleep(wait)

        raise last_exc or RuntimeError("All LLM providers exhausted")


class FailoverLLM:
    def __init__(self, temperature: float = 0.2, preferred_order=None):
        self.temperature = temperature
        self.preferred_order = preferred_order

    def with_structured_output(self, schema):
        return _StructuredFailoverRunner(self.temperature, schema, self.preferred_order)

    def invoke_json_mode(self, messages, schema=None, **kwargs):
        last_exc = None
        providers = _available_providers(self.preferred_order)

        # Ensure the prompt demands JSON output
        json_instruction = "\n\nYou MUST respond with ONLY a valid JSON object. No markdown fences, no additional text."
        if messages and hasattr(messages[0], 'content') and isinstance(messages[0], SystemMessage):
            if "json" not in messages[0].content.lower():
                messages[0].content += json_instruction
        else:
            # If no system message, prepend one
            messages = [SystemMessage(content=f"Respond with JSON only.{json_instruction}")] + list(messages)

        for attempt, name in enumerate(providers):
            model = _get_client(name, self.temperature)
            if model is None:
                continue
            try:
                response = model.invoke(
                    messages,
                    response_format={"type": "json_object"},
                    **kwargs
                )
                raw = _extract_json(response.content)
                parsed = json.loads(raw)

                if schema:
                    result = schema.model_validate(parsed)
                else:
                    result = parsed

                _call_counts[name] += 1
                return result

            except Exception as e:
                print(f"[llm_client] {name} json_mode failed: {type(e).__name__}: {e}")
                last_exc = e
                if _is_rate_limit_error(e):
                    time.sleep(min(2 ** attempt, 4))

        raise last_exc or RuntimeError("All LLM providers exhausted for JSON mode")

    def invoke(self, prompt, **kwargs):
        last_exc = None
        providers = _available_providers(self.preferred_order)
        for attempt, name in enumerate(providers):
            model = _get_client(name, self.temperature)
            if model is None:
                continue
            try:
                result = model.invoke(prompt, **kwargs)
                _call_counts[name] += 1
                return result
            except Exception as e:
                print(f"[llm_client] {name} failed: {type(e).__name__}: {e}")
                last_exc = e
                if _is_rate_limit_error(e):
                    wait = min(2 ** attempt, 4)
                    time.sleep(wait)
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