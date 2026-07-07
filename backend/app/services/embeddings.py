from sentence_transformers import SentenceTransformer
from app.config import settings

_model = SentenceTransformer(settings.EMBEDDING_MODEL)

def embed_texts(texts: list[str]) -> list[list[float]]:
    return _model.encode(texts, convert_to_numpy=True).tolist()

def similarity(a: list[float], b: list[float]) -> float:
    import numpy as np
    a, b = np.array(a), np.array(b)
    return float(a.dot(b) / (np.linalg.norm(a) * np.linalg.norm(b)))
