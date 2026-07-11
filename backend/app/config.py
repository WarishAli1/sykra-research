from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    GROQ_API_KEY: str = ""
    GROQ_API_KEY_2: str = ""
    CHROMA_PERSIST_DIR: str = "app/db/vector_db"
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    TOP_K_PAPERS_MAX: int = 8
    TOP_K_PAPERS_MIN: int = 3
    MIN_FINAL_SCORE: float = 0.45
    COVERAGE_THRESHOLD: float = 0.35
    ARXIV_MAX_RESULTS: int = 15

    class Config:
        env_file = ".env"


settings = Settings()
