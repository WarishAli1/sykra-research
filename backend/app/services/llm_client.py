import json
import re
import time

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from langchain_cerebras import ChatCerebras

from app.config import settings


def _extract_json(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^`(?:json)?\s*|\s*`$", "", text, flags=re.MULTILINE)
    match = re.search(r"{.*}", text, re.DOTALL)
    return match.group(0) if match else text


def _is_rate_limit_error(e: Exception) -> bool:
    msg = str(e).lower()
    return (
        "rate_limit" in msg
        or "429" in msg
        or "413" in msg
        or "quota" in msg
        or "capacity" in msg
        or "too many requests" in msg
    )


_call_counts = {
    "groq_key1": 0,
    "groq_key2": 0,
}

_client_cache: dict[tuple[str, float, str], object] = {}


TASK_CATEGORY = {
    "fast": "fast",
    "light": "fast",
    "structured": "fast",
    "default": "default",
    "strong": "strong",
    "synthesis": "strong",
}

ORDER_MAP = {
    "fast": ["groq_key1", "groq_key2"],
    "light": ["groq_key1", "groq_key2"],
    "structured": ["groq_key1", "groq_key2"],
    "default": ["groq_key1", "groq_key2"],
    "strong": ["groq_key1", "groq_key2"],
    "synthesis": ["groq_key1", "groq_key2"],
}


def _model_for_provider(provider_name: str, category: str) -> str:
    category = category if category in ("fast", "default", "strong") else "default"

    if provider_name.startswith("groq"):
        return str(getattr(settings, f"GROQ_MODEL_{category.upper()}", settings.GROQ_MODEL_DEFAULT))

    return settings.GROQ_MODEL_DEFAULT


def _get_client(name: str, temperature: float, model: str):
    key = (name, temperature, model)
    client = _client_cache.get(key)

    if client is not None:
        return client

    if name == "groq_key1":
        api_key = settings.GROQ_API_KEY
        if not api_key:
            return None
        client = ChatGroq(
            api_key=api_key,
            model=model,
            temperature=temperature,
            request_timeout=30,
        )

    elif name == "groq_key2":
        api_key = settings.GROQ_API_KEY_2
        if not api_key:
            return None
        client = ChatGroq(
            api_key=api_key,
            model=model,
            temperature=temperature,
            request_timeout=30,
        )

    else:
        return None

    if client is not None:
        _client_cache[key] = client

    return client


def _available_providers(preferred_order: list[str] | None) -> list[str]:
    order = preferred_order or list(_call_counts.keys())

    configured = {
        "groq_key1": bool(settings.GROQ_API_KEY),
        "groq_key2": bool(settings.GROQ_API_KEY_2)
    }

    return [name for name in order if configured.get(name)]


class _StructuredFailoverRunner:
    def __init__(self, temperature: float, schema, category: str, preferred_order=None):
        self.temperature = temperature
        self.schema = schema
        self.category = category
        self.preferred_order = preferred_order

    def invoke(self, prompt, **kwargs):
        last_exc = None
        providers = _available_providers(self.preferred_order)

        for attempt, name in enumerate(providers):
            model_name = _model_for_provider(name, self.category)
            model = _get_client(name, self.temperature, model_name)

            if model is None:
                continue

            try:
                result = model.with_structured_output(self.schema).invoke(prompt, **kwargs)
                _call_counts[name] += 1
                return result

            except Exception as e:
                print(f"[llm_client] {name}:{model_name} structured failed: {type(e).__name__}: {e}")
                last_exc = e

                if _is_rate_limit_error(e):
                    wait = min(2 ** attempt, 4)
                    time.sleep(wait)

        for attempt, name in enumerate(providers):
            model_name = _model_for_provider(name, self.category)
            model = _get_client(name, self.temperature, model_name)

            if model is None:
                continue

            try:
                schema_json = self.schema.model_json_schema()

                json_prompt = list(prompt) + [
                    HumanMessage(
                        content=(
                            "Respond with ONLY a JSON object matching this schema, "
                            f"no markdown fences, no preamble:\n{json.dumps(schema_json)}"
                        )
                    )
                ]

                raw = model.invoke(json_prompt, **kwargs)
                parsed = json.loads(_extract_json(raw.content))
                result = self.schema.model_validate(parsed)

                _call_counts[name] += 1
                return result

            except Exception as e2:
                print(f"[llm_client] {name}:{model_name} JSON fallback failed: {type(e2).__name__}: {e2}")
                last_exc = e2

                if _is_rate_limit_error(e2):
                    wait = min(2 ** attempt, 4)
                    time.sleep(wait)

        raise last_exc or RuntimeError("All LLM providers exhausted")


class FailoverLLM:
    def __init__(self, temperature: float = 0.2, category: str = "default", preferred_order=None):
        self.temperature = temperature
        self.category = category
        self.preferred_order = preferred_order

    def with_structured_output(self, schema):
        return _StructuredFailoverRunner(
            temperature=self.temperature,
            schema=schema,
            category=self.category,
            preferred_order=self.preferred_order,
        )

    def invoke_json_mode(self, messages, schema=None, **kwargs):
        last_exc = None
        providers = _available_providers(self.preferred_order)

        json_instruction = (
            "\n\nYou MUST respond with ONLY a valid JSON object. "
            "No markdown fences, no additional text."
        )

        if messages and hasattr(messages[0], "content") and isinstance(messages[0], SystemMessage):
            if "json" not in messages[0].content.lower():
                messages[0].content += json_instruction
        else:
            messages = [SystemMessage(content=f"Respond with JSON only.{json_instruction}")] + list(messages)

        for attempt, name in enumerate(providers):
            model_name = _model_for_provider(name, self.category)
            model = _get_client(name, self.temperature, model_name)

            if model is None:
                continue

            try:
                response = model.invoke(
                    messages,
                    response_format={"type": "json_object"},
                    **kwargs,
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
                print(f"[llm_client] {name}:{model_name} json_mode failed: {type(e).__name__}: {e}")
                last_exc = e

                if _is_rate_limit_error(e):
                    time.sleep(min(2 ** attempt, 4))

        raise last_exc or RuntimeError("All LLM providers exhausted for JSON mode")

    def invoke(self, prompt, **kwargs):
        last_exc = None
        providers = _available_providers(self.preferred_order)

        for attempt, name in enumerate(providers):
            model_name = _model_for_provider(name, self.category)
            model = _get_client(name, self.temperature, model_name)

            if model is None:
                continue

            try:
                result = model.invoke(prompt, **kwargs)
                _call_counts[name] += 1
                return result

            except Exception as e:
                print(f"[llm_client] {name}:{model_name} failed: {type(e).__name__}: {e}")
                last_exc = e

                if _is_rate_limit_error(e):
                    wait = min(2 ** attempt, 4)
                    time.sleep(wait)

        raise last_exc or RuntimeError("All LLM providers exhausted")


def get_llm(temperature: float = 0.2, task: str = "default"):
    category = TASK_CATEGORY.get(task, "default")
    preferred_order = ORDER_MAP.get(task) or ORDER_MAP.get(category) or ORDER_MAP["default"]

    return FailoverLLM(
        temperature=temperature,
        category=category,
        preferred_order=preferred_order,
    )


    def stream(self, prompt, **kwargs):
        """
        Stream tokens from the first available provider.
        Falls back to next provider on error.
        """
        providers = _available_providers(self.preferred_order)
        last_exc = None
        for name in providers:
            model_name = _model_for_provider(name, self.category)
            model = _get_client(name, self.temperature, model_name)
            if model is None:
                continue
            try:
                yielded = False
                for chunk in model.stream(prompt, **kwargs):
                    yielded = True
                    yield chunk
                if yielded:
                    _call_counts[name] += 1
                return
            except Exception as e:
                print(f"[llm_client] {name}:{model_name} stream failed: {type(e).__name__}: {e}")
                last_exc = e
        raise last_exc or RuntimeError("All LLM providers exhausted for streaming")
        

def get_provider_usage() -> dict:
    return dict(_call_counts)