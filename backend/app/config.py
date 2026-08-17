from pathlib import Path
from pydantic_settings import BaseSettings


_BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    GROQ_API_KEY: str = ""
    GROQ_API_KEY_2: str = ""

    CHROMA_PERSIST_DIR: str = str(_BACKEND_DIR / "app" / "db" / "vector_db")
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    LOGO_PATH: str = str(_BACKEND_DIR / "logo" / "sykra-icon.png")
    MATHJAX_JS_PATH: str = str(
        _BACKEND_DIR / "node_modules" / "mathjax" / "es5" / "tex-svg.js"
    )

    NEO4J_URI: str = ""
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = ""
    BACKEND_PUBLIC_URL: str = "http://localhost:8000"

    TOP_K_PAPERS_NORMAL_MIN: int = 4
    TOP_K_PAPERS_NORMAL_MAX: int = 7
    TOP_K_PAPERS_RESEARCH_MIN: int = 8
    TOP_K_PAPERS_RESEARCH_MAX: int = 15

    TOP_K_PAPERS_MAX: int = 15
    TOP_K_PAPERS_MIN: int = 4
    TOP_K_PAPERS_LOW: int = 4
    TOP_K_PAPERS_MEDIUM: int = 6
    TOP_K_PAPERS_HIGH: int = 8

    MIN_FINAL_SCORE: float = 0.42
    COVERAGE_THRESHOLD: float = 0.35
    ARXIV_MAX_RESULTS: int = 10

    REPORT_TARGET_WORDS_LOW: int = 700
    REPORT_TARGET_WORDS_MEDIUM: int = 1800
    REPORT_TARGET_WORDS_HIGH: int = 3200

    REPORT_MODULE_THRESHOLD_LOW: int = 35
    REPORT_MODULE_THRESHOLD_MEDIUM: int = 30
    REPORT_MODULE_THRESHOLD_HIGH: int = 25
    REPORT_MAX_MODULES_LOW: int = 4
    REPORT_MAX_MODULES_MEDIUM: int = 6
    REPORT_MAX_MODULES_HIGH: int = 8

    REPORT_PLAN_TIMEOUT: int = 4
    REPORT_SUMMARY_TIMEOUT_NORMAL: int = 6
    REPORT_SUMMARY_TIMEOUT_DEEP: int = 10
    REPORT_SECTION_TIMEOUT_NORMAL: int = 10
    REPORT_SECTION_TIMEOUT_DEEP: int = 16
    REPORT_CRITIQUE_TIMEOUT: int = 6
    REPORT_COMPARE_TIMEOUT: int = 6
    REPORT_CHART_TIMEOUT: int = 10
    REPORT_REVISE_TIMEOUT: int = 12
    REPORT_VERIFY_TIMEOUT: int = 8

    GRAPH_ENABLED: bool = True
    GRAPH_CACHE_DIR: str = str(_BACKEND_DIR / "app" / "db" / "graph_cache")
    GRAPH_NEO4J_MIRROR: bool = True
    GRAPH_OPENALEX_CITATIONS: bool = True
    GRAPH_MAX_PAPERS: int = 60
    GRAPH_MAX_CONCEPTS_PER_PAPER: int = 6
    GRAPH_MAX_METHODS_PER_PAPER: int = 6
    GRAPH_MAX_DATASETS_PER_PAPER: int = 4
    GRAPH_ABSTRACT_CHARS_FOR_EXTRACTION: int = 1200
    GRAPH_SIMILAR_EDGE_THRESHOLD: float = 0.50
    GRAPH_MAX_SIMILAR_EDGES_PER_PAPER: int = 6

    SSE_CHUNK_DELAY_SECONDS: float = 0.0
    SSE_WORDS_PER_FRAME: int = 10

    SEMANTIC_CACHE_ENABLED: bool = False
    SEMANTIC_CACHE_SEARCH_SIMILARITY: float = 0.92
    SEMANTIC_CACHE_TTL_SECONDS: int = 3600
    REQUEST_DEDUP_ENABLED: bool = True

    GROQ_MODEL_FAST: str = "qwen/qwen3.6-27b"
    GROQ_MODEL_DEFAULT: str = "qwen/qwen3.6-27b"
    GROQ_MODEL_STRONG: str = "openai/gpt-oss-120b"

    LLM_THINKING_CONTROL_MAP: str = (
        "qwen=Do not think or output internal reasoning. Return only final answer."
    )
    GROQ_REASONING_MODEL_SUBSTRINGS: str = "qwen/qwen3,qwen3"
    GROQ_REASONING_EFFORT: str = "none"
    
    ENABLE_POST_ENRICHMENT: bool = False
    LLM_RERANK_ENABLED: bool = True
    LLM_VERIFY_ENABLED: bool = True
    LLM_REVISE_ENABLED: bool = True
    LLM_ANSWER_SPEC_ENABLED: bool = True
    LLM_MAX_PROMPT_TOKENS: int = 5500
    RERANK_MAX_CANDIDATES: int = 10
    GROQ_TPM_LIMIT: int = 8000
    LLM_MAX_OUTPUT_TOKENS: int = 4096
    
    EVIDENCE_SUFFICIENCY_THRESHOLD: float = 0.60
    EVIDENCE_SUFFICIENCY_WARNING_THRESHOLD: float = 0.85

    RESEARCH_DISCLAIMER: str = (
        "Sykra can make mistakes. Verify important claims independently "
        "and treat this research as a starting baseline."
    )

    class Config:
        env_file = str(_BACKEND_DIR / ".env")


settings = Settings()