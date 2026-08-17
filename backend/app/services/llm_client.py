import json
import re
import time
import threading
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from langchain_cerebras import ChatCerebras

from app.config import settings


_RATE_LIMIT_COOLDOWN_SECONDS = 60
_balance_lock = threading.Lock()
_provider_cooldown_until: dict[str, float] = {}

def _provider_in_cooldown(name: str) -> bool:
    return time.time() < _provider_cooldown_until.get(name, 0.0)

def _mark_provider_cooldown(name: str) -> None:
    with _balance_lock:
        _provider_cooldown_until[name] = (
            time.time() + _RATE_LIMIT_COOLDOWN_SECONDS
        )

def is_llm_rate_limited() -> bool:
    """True only when EVERY configured key is cooling down.
    One key hitting a 429 must no longer disable LLM steps —
    the other account still has its own fresh quota."""
    configured = [
        n for n in _call_counts
        if (n == "groq_key1" and settings.GROQ_API_KEY)
        or (n == "groq_key2" and settings.GROQ_API_KEY_2)
    ]
    if not configured:
        return False
    return all(_provider_in_cooldown(n) for n in configured)

def _record_success(name: str) -> None:
    with _balance_lock:
        _call_counts[name] = _call_counts.get(name, 0) + 1



def _extract_json(text: str) -> str:
    """
    Model-agnostic JSON recovery.
    Scans for the first position where a complete JSON object parses.
    Survives leading thinking text, trailing commentary, and multiple
    brace groups — the classic failure signatures of thinking models.
    """
    text = (text or "").strip()
    text = re.sub(r"^`(?:json)?\s*|\s*`$", "", text, flags=re.MULTILINE)

    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            obj, _ = decoder.raw_decode(text, match.start())
            return json.dumps(obj)
        except json.JSONDecodeError:
            continue

    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group(0) if match else text



def _estimate_tokens(text: str) -> int:
    return max(0, len(text or "") // 3)


def _is_request_too_large(e: Exception) -> bool:
    msg = str(e).lower()
    return "413" in msg or "request too large" in msg or "too large for model" in msg


def _enforce_prompt_budget(messages, reserve_tokens: int = 0):
    """Keep (prompt estimate + output reserve) under the provider TPM quota."""
    tpm = int(getattr(settings, "GROQ_TPM_LIMIT", 8000))
    budget = min(
        int(getattr(settings, "LLM_MAX_PROMPT_TOKENS", 5500)),
        tpm - int(reserve_tokens) - 256,
    )
    if not isinstance(messages, list):
        return messages
    sizes = [
        _estimate_tokens(m.content)
        if isinstance(getattr(m, "content", None), str) else 0
        for m in messages
    ]
    total = sum(sizes)
    if total <= budget:
        return messages
    idx = sizes.index(max(sizes))
    m = messages[idx]
    keep_chars = max(800, len(m.content) - (total - budget + 250) * 3)
    trimmed = m.content[:keep_chars] + "\n[...trimmed to fit token budget...]"
    out = list(messages)
    out[idx] = type(m)(content=trimmed)
    return out


def _is_rate_limit_error(e: Exception) -> bool:
    msg = str(e).lower()
    return (
        "rate_limit" in msg
        or "429" in msg
        or "quota" in msg
        or "capacity" in msg
        or "too many requests" in msg
    )


def _is_json_mode_rejection(e: Exception) -> bool:
    """
    Detects when a provider's native structured-output / JSON mode rejected
    the request or generation server-side (e.g. Groq's json_validate_failed,
    or a 400 tied to response_format), as opposed to a network error, auth
    error, or content-policy refusal. These are worth retrying via a
    prompted-JSON fallback on the SAME provider/model, since the failure is
    specific to the native-mode constraint, not the model's capability.
    """
    msg = str(e).lower()
    return (
        "json_validate_failed" in msg
        or "response_format" in msg
        or ("400" in msg and "json" in msg)
        or "failed to validate json" in msg
    )


def _is_empty_generation_failure(e: Exception) -> bool:
    """
    Detects Groq's specific 'failed_generation': '' signature -- meaning the
    model produced NO output at all before its own validator rejected the
    call, as opposed to producing malformed-but-real JSON. This distinction
    matters: a prompted-JSON retry (same model, same prompt, just without
    response_format) is only likely to help when the model actually
    generated something we can re-parse. When generation was empty, retrying
    the same messages against the same model is very likely to fail the
    same way again -- it costs a full extra timeout round-trip for
    essentially zero recovery chance. Skip the fallback in that case and
    move to the next provider (or give up) faster instead.
    """
    msg = str(e)
    return "'failed_generation': ''" in msg or '"failed_generation": ""' in msg


def _parse_thinking_control_map(raw: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for chunk in (raw or "").split(","):
        if "=" not in chunk:
            continue
        needle, directive = chunk.split("=", 1)
        needle = needle.strip().lower()
        directive = directive.strip()
        if needle and directive:
            pairs.append((needle, directive))
    return pairs


_THINKING_CONTROL_PAIRS = _parse_thinking_control_map(
    getattr(settings, "LLM_THINKING_CONTROL_MAP", "")
)


def _thinking_directive_for(model_name: str) -> str | None:
    """
    Data-driven lookup: returns the thinking-disable directive for a model
    family if one is configured, else None. Unknown / future models simply
    get no directive — the pipeline still works via Layer 1 fallbacks.
    """
    name = (model_name or "").lower()
    for needle, directive in _THINKING_CONTROL_PAIRS:
        if needle and needle in name:
            return directive
    return None


def _apply_thinking_control(messages, model_name: str):
    """
    Append the configured directive (if any) to the last human message.
    No-op for every model without an entry in LLM_THINKING_CONTROL_MAP.
    """
    directive = _thinking_directive_for(model_name)
    if not directive:
        return messages
    if isinstance(messages, str):
        if directive in messages:
            return messages
        return messages + "\n" + directive
    out = list(messages)
    for i in range(len(out) - 1, -1, -1):
        msg = out[i]
        if isinstance(msg, HumanMessage):
            content = msg.content
            if isinstance(content, str) and directive not in content:
                out[i] = HumanMessage(content=content + "\n" + directive)
            break
    return out


def _groq_reasoning_model_needles() -> list[str]:
    raw = str(getattr(settings, "GROQ_REASONING_MODEL_SUBSTRINGS", "") or "")
    needles = [part.strip().lower() for part in raw.split(",") if part.strip()]
    return needles or ["qwen/qwen3", "qwen3"]


def _groq_reasoning_kwargs(model_name: str) -> dict:
    effort = str(getattr(settings, "GROQ_REASONING_EFFORT", "none") or "").strip()
    if not effort:
        return {}

    name = (model_name or "").lower()
    needles = _groq_reasoning_model_needles()

    if any(needle in name for needle in needles):
        return {"reasoning_effort": effort}

    return {}


def _create_chat_groq(api_key: str, model: str, temperature: float):
    base = {
        "api_key": api_key,
        "model": model,
        "temperature": temperature,
        "request_timeout": 30,
    }

    reasoning_kwargs = _groq_reasoning_kwargs(model)
    if not reasoning_kwargs:
        return ChatGroq(**base)

    print(
        f"[llm_client] Groq reasoning control for {model}: {reasoning_kwargs}"
    )

    fields = getattr(ChatGroq, "model_fields", {})
    attempts = []

    if "reasoning_effort" in fields:
        attempts.append({**base, **reasoning_kwargs})

    if "model_kwargs" in fields:
        attempts.append({**base, "model_kwargs": reasoning_kwargs})

    if "extra_body" in fields:
        attempts.append({**base, "extra_body": reasoning_kwargs})

    attempts.extend(
        [
            {**base, "model_kwargs": reasoning_kwargs},
            {**base, "extra_body": reasoning_kwargs},
            {**base, **reasoning_kwargs},
        ]
    )

    seen_attempts = []
    last_error = None

    for kwargs in attempts:
        if any(kwargs == seen for seen in seen_attempts):
            continue
        seen_attempts.append(kwargs)

        try:
            return ChatGroq(**kwargs)
        except Exception as e:
            last_error = e

    print(
        "[llm_client] warning: could not attach reasoning kwargs "
        f"{reasoning_kwargs} for {model}: "
        f"{type(last_error).__name__}: {last_error}. Using base client."
    )

    return ChatGroq(**base)

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
        client = _create_chat_groq(api_key, model, temperature)

    elif name == "groq_key2":
        api_key = settings.GROQ_API_KEY_2
        if not api_key:
            return None
        client = _create_chat_groq(api_key, model, temperature)

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
    available = [name for name in order if configured.get(name)]
    with _balance_lock:
        available.sort(
            key=lambda n: (
                _provider_in_cooldown(n),
                _call_counts.get(n, 0),
            )
        )
    return available


class _StructuredFailoverRunner:
    def __init__(self, temperature: float, schema, category: str, preferred_order=None):
        self.temperature = temperature
        self.schema = schema
        self.category = category
        self.preferred_order = preferred_order

    def invoke(self, prompt, **kwargs):
        last_exc = None
        providers = _available_providers(self.preferred_order)

        schema_json = self.schema.model_json_schema()

        json_prompt = list(prompt) + [
            HumanMessage(
                content=(
                    "Respond with ONLY a valid JSON object matching this schema. "
                    "Do not use markdown fences. "
                    "Do not include any explanation or additional text.\n\n"
                    f"JSON Schema:\n{json.dumps(schema_json)}"
                )
            )
        ]
        json_prompt = _enforce_prompt_budget(json_prompt, reserve_tokens=4096)

        for attempt, name in enumerate(providers):
            model_name = _model_for_provider(name, self.category)
            model = _get_client(name, self.temperature, model_name)

            if model is None:
                continue

            try:
                kwargs.setdefault("max_tokens", 4096)
                raw = model.invoke(
                    _apply_thinking_control(json_prompt, model_name),
                    **kwargs,
                )
                parsed = json.loads(_extract_json(raw.content))
                result = self.schema.model_validate(parsed)

                _record_success(name)
                return result

            except Exception as e:
                print(
                    f"[llm_client] {name}:{model_name} "
                    f"structured JSON failed: {type(e).__name__}: {e}"
                )
                last_exc = e

                if _is_rate_limit_error(e):
                    _mark_provider_cooldown(name)
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
        messages = _enforce_prompt_budget(messages, reserve_tokens=4096)
        for attempt, name in enumerate(providers):
            model_name = _model_for_provider(name, self.category)
            model = _get_client(name, self.temperature, model_name)

            if model is None:
                continue

            try:
                kwargs.setdefault("max_tokens", 4096)
                response = model.invoke(
                    _apply_thinking_control(messages, model_name),
                    response_format={"type": "json_object"},
                    **kwargs,
                )

                raw = _extract_json(response.content)
                parsed = json.loads(raw)

                if schema:
                    result = schema.model_validate(parsed)
                else:
                    result = parsed

                _record_success(name)
                return result

            except Exception as e:
                print(f"[llm_client] {name}:{model_name} json_mode failed: {type(e).__name__}: {e}")
                last_exc = e

                if _is_rate_limit_error(e):
                    _mark_provider_cooldown(name)
                    time.sleep(min(2 ** attempt, 4))
                    continue

                if _is_json_mode_rejection(e):
                    if _is_empty_generation_failure(e):
                        print(
                            f"[llm_client] {name}:{model_name} empty generation in "
                            f"json_mode; switching to prompted JSON fallback."
                        )
                        last_exc = e
                        break
                    print(
                        f"[llm_client] {name}:{model_name} json_mode rejected; "
                        f"will try prompted JSON fallback."
                    )
                    last_exc = e
                    continue

        for name in providers:
            model_name = _model_for_provider(name, self.category)
            model = _get_client(name, self.temperature, model_name)
            if model is None:
                continue
            try:
                raw = model.invoke(
                    _apply_thinking_control(messages, model_name),
                    **kwargs,
                )
                parsed = json.loads(_extract_json(raw.content))
                if schema:
                    result = schema.model_validate(parsed)
                else:
                    result = parsed
                _record_success(name)
                print(
                    f"[llm_client] {name}:{model_name} JSON recovered via "
                    f"prompted fallback"
                )
                return result
            except Exception as e:
                print(
                    f"[llm_client] {name}:{model_name} prompted JSON fallback "
                    f"failed: {type(e).__name__}: {e}"
                )
                last_exc = e

        raise last_exc or RuntimeError("All LLM providers exhausted for JSON mode")

    def invoke(self, prompt, **kwargs):
        last_exc = None
        providers = _available_providers(self.preferred_order)
        kwargs.setdefault(
            "max_tokens",
            int(getattr(settings, "LLM_MAX_OUTPUT_TOKENS", 4096)),
        )
        prompt = _enforce_prompt_budget(
            prompt, reserve_tokens=kwargs["max_tokens"]
        )
        for attempt, name in enumerate(providers):
            model_name = _model_for_provider(name, self.category)
            model = _get_client(name, self.temperature, model_name)
            if model is None:
                continue
            try:
                result = model.invoke(
                    _apply_thinking_control(prompt, model_name),
                    **kwargs,
                )
                _record_success(name)
                return result
            except Exception as e:
                print(f"[llm_client] {name}:{model_name} failed: {type(e).__name__}: {e}")
                last_exc = e
                if _is_request_too_large(e):
                    break 
                if _is_rate_limit_error(e):
                    _mark_provider_cooldown(name)
                    wait = min(2 ** attempt, 4)
                    time.sleep(wait)
        raise last_exc or RuntimeError("All LLM providers exhausted")

    def stream(self, prompt, **kwargs):
        """
        Stream tokens from the first available provider.
        Falls back to next provider on error.
        """
        providers = _available_providers(self.preferred_order)
        last_exc = None
        kwargs.setdefault(
            "max_tokens",
            int(getattr(settings, "LLM_MAX_OUTPUT_TOKENS", 4096)),
        )
        prompt = _enforce_prompt_budget(
            prompt, reserve_tokens=kwargs["max_tokens"]
        )
        for name in providers:
            model_name = _model_for_provider(name, self.category)
            model = _get_client(name, self.temperature, model_name)
            if model is None:
                continue
            try:
                yielded = False
                for chunk in model.stream(
                    _apply_thinking_control(prompt, model_name),
                    **kwargs,
                ):
                    yielded = True
                    yield chunk
                if yielded:
                    _record_success(name)
                return
            except Exception as e:
                print(f"[llm_client] {name}:{model_name} stream failed: {type(e).__name__}: {e}")
                last_exc = e
                if _is_request_too_large(e):
                    break
                if _is_rate_limit_error(e):
                    _mark_provider_cooldown(name)
                    wait = min(2 ** providers.index(name), 4)
                    time.sleep(wait)
        raise last_exc or RuntimeError("All LLM providers exhausted for streaming")


def get_llm(temperature: float = 0.2, task: str = "default"):
    category = TASK_CATEGORY.get(task, "default")
    preferred_order = ORDER_MAP.get(task) or ORDER_MAP.get(category) or ORDER_MAP["default"]

    return FailoverLLM(
        temperature=temperature,
        category=category,
        preferred_order=preferred_order,
    )

        

def get_provider_usage() -> dict:
    return dict(_call_counts)