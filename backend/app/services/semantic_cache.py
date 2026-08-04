import hashlib
import json
import time

from app.config import settings
from app.services.embeddings import embed_texts
from app.services.vector_store import vector_store


_COLLECTION_NAME = "semantic_cache"


def _get_collection():
    return vector_store.client.get_or_create_collection(
        name=_COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def normalize_query(query: str) -> str:
    return " ".join((query or "").strip().lower().split())


def make_scope_key(query: str, scope: str) -> str:
    normalized = normalize_query(query)
    raw = f"{scope}:{normalized}"
    return hashlib.sha256(raw.encode()).hexdigest()


def strip_papers_for_cache(papers: list[dict]) -> list[dict]:
    """
    Remove large/runtime-only fields before storing search results.
    """
    cleaned = []

    for p in papers or []:
        if not isinstance(p, dict):
            continue

        item = dict(p)

        item.pop("abstract_vec", None)
        item.pop("_abstract_vec", None)
        item.pop("_title_embed", None)
        item.pop("_no_abstract", None)

        cleaned.append(item)

    return cleaned


def get_search_cache(
    query: str,
    scope: str,
    similarity_threshold: float | None = None,
    ttl_seconds: int | None = None,
) -> dict | None:
    if not settings.SEMANTIC_CACHE_ENABLED:
        return None

    similarity_threshold = similarity_threshold or settings.SEMANTIC_CACHE_SEARCH_SIMILARITY
    ttl_seconds = ttl_seconds or settings.SEMANTIC_CACHE_TTL_SECONDS

    try:
        col = _get_collection()
        query_embedding = embed_texts([normalize_query(query)])[0]

        result = col.query(
            query_embeddings=[query_embedding],
            n_results=1,
            where={"scope": scope},
        )

        ids = result.get("ids") or [[]]
        documents = result.get("documents") or [[]]
        distances = result.get("distances") or [[]]
        metadatas = result.get("metadatas") or [[]]

        if not ids or not ids[0]:
            return None

        distance = float(distances[0][0]) if distances and distances[0] else 1.0
        similarity = max(0.0, 1.0 - distance)

        if similarity < similarity_threshold:
            return None

        metadata = metadatas[0][0] if metadatas and metadatas[0] else {}
        created = float(metadata.get("created", 0.0))

        if ttl_seconds and created and (time.time() - created) > ttl_seconds:
            return None

        payload = json.loads(documents[0][0]) if documents and documents[0] else {}

        if not isinstance(payload, dict):
            return None

        payload["_cache_similarity"] = similarity
        return payload

    except Exception as e:
        print(f"[semantic_cache] get_search_cache failed: {type(e).__name__}: {e}")
        return None


def set_search_cache(
    query: str,
    scope: str,
    raw_search_results: list[dict],
    query_embedding: list[float] | None = None,
) -> None:
    if not settings.SEMANTIC_CACHE_ENABLED:
        return

    try:
        col = _get_collection()

        normalized = normalize_query(query)
        embedding = query_embedding or embed_texts([normalized])[0]

        payload = {
            "query": normalized,
            "scope": scope,
            "raw_search_results": strip_papers_for_cache(raw_search_results),
            "query_embedding": embedding,
            "cached_at": time.time(),
        }

        doc = json.dumps(payload)
        cache_id = make_scope_key(query, scope)

        col.upsert(
            ids=[cache_id],
            embeddings=[embedding],
            documents=[doc],
            metadatas=[
                {
                    "scope": scope,
                    "created": time.time(),
                    "query": normalized[:500],
                }
            ],
        )

    except Exception as e:
        print(f"[semantic_cache] set_search_cache failed: {type(e).__name__}: {e}")