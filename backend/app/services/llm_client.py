from langchain_groq import ChatGroq
from app.config import settings

GROQ_KEYS = [k for k in [settings.GROQ_API_KEY, settings.GROQ_API_KEY_2] if k]


def _is_rate_limit_error(e: Exception) -> bool:
    msg = str(e).lower()
    return "rate_limit" in msg or "429" in msg or "quota" in msg


class _StructuredFailoverRunner:
    def __init__(self, model, temperature, schema):
        self.model = model
        self.temperature = temperature
        self.schema = schema

    def invoke(self, prompt):
        last_exc = None
        for key in GROQ_KEYS:
            try:
                llm = ChatGroq(api_key=key, model=self.model, temperature=self.temperature)
                return llm.with_structured_output(self.schema).invoke(prompt)
            except Exception as e:
                if _is_rate_limit_error(e):
                    last_exc = e
                    continue
                raise
        raise last_exc or RuntimeError("All Groq keys exhausted")


class FailoverLLM:
    def __init__(self, model="llama-3.3-70b-versatile", temperature=0.2):
        self.model = model
        self.temperature = temperature

    def with_structured_output(self, schema):
        return _StructuredFailoverRunner(self.model, self.temperature, schema)

    def invoke(self, prompt):
        last_exc = None
        for key in GROQ_KEYS:
            try:
                return ChatGroq(api_key=key, model=self.model, temperature=self.temperature).invoke(prompt)
            except Exception as e:
                if _is_rate_limit_error(e):
                    last_exc = e
                    continue
                raise
        raise last_exc


def get_llm(temperature: float = 0.2):
    return FailoverLLM(temperature=temperature)
