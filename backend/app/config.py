from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    GROQ_API_KEY: str = ""
    CHROMA_PERSIST_DIR: str = "app/db/vector_db"
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    TOP_K_PAPERS: int = 5
    ARXIV_MAX_RESULTS: int = 15

    class Config:
        env_file = ".env"

settings = Settings()
