import numpy as np
from chromadb.utils import embedding_functions
from app.config import settings

_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name=settings.EMBEDDING_MODEL
)


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    return _ef(texts)


def similarity(vec_a: list[float], vec_b: list[float]) -> float:
    a = np.array(vec_a)
    b = np.array(vec_b)
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    if norm == 0:
        return 0.0
    return float(np.dot(a, b) / norm)
