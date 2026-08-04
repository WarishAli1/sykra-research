import hashlib

import chromadb

from chromadb.config import Settings as ChromaSettings
from chromadb.utils import embedding_functions

from app.config import settings
from app.services.chunking import chunk_text


_paper_embed_collection = None


class VectorStore:
    def __init__(self):
        self.client = chromadb.PersistentClient(
            path=settings.CHROMA_PERSIST_DIR,
            settings=ChromaSettings(anonymized_telemetry=False),
        )

        self.embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=settings.EMBEDDING_MODEL
        )

        self.collection = self.client.get_or_create_collection(
            name="papers",
            embedding_function=self.embed_fn,
        )

    def _chunk_id(self, paper_link: str, chunk_index: int) -> str:
        base = hashlib.sha256(paper_link.encode()).hexdigest()[:16]
        return f"{base}_{chunk_index}"

    def upsert_paper(self, paper: dict, session_id: str):
        text = paper.get("text") or paper.get("summary", "")

        if not text.strip():
            return

        chunks = chunk_text(text)

        if not chunks:
            return

        ids = [
            self._chunk_id(paper["link"], i)
            for i in range(len(chunks))
        ]

        authors_str = "|".join(paper.get("authors", []))

        metadatas = [
            {
                "session_id": session_id,
                "title": paper["title"],
                "link": paper["link"],
                "source": paper.get("source", "unknown"),
                "paper_type": paper.get("paper_type", "application"),
                "published": paper.get("published", ""),
                "authors": authors_str,
                "chunk_index": i,
                "openalex_id": paper.get("openalex_id", "") or "",
                "citation_count": int(paper.get("citation_count", 0) or 0)
            }
            for i in range(len(chunks))
        ]

        self.collection.upsert(
            ids=ids,
            documents=chunks,
            metadatas=metadatas,
        )

    def query_session(
        self,
        query_text: str,
        session_id: str,
        n_results: int = 5,
    ) -> dict:
        return self.collection.query(
            query_texts=[query_text],
            n_results=n_results,
            where={"session_id": session_id},
        )

    def query_uploaded_documents(
        self,
        session_id: str,
        query: str,
        k: int = 5,
    ) -> dict:
        return self.query_session(
            query,
            session_id,
            n_results=k,
        )

    def get_session_papers(self, session_id: str) -> list[dict]:
        results = self.collection.get(
            where={"session_id": session_id}
        )

        seen = {}

        for meta in results.get("metadatas", []):
            meta = dict(meta)

            authors_raw = meta.get("authors", "")
            meta["authors"] = authors_raw.split("|") if authors_raw else []

            seen[meta["link"]] = meta

        return list(seen.values())

    def get_session_history(
        self,
        session_id: str,
        limit: int = 20,
    ) -> dict:
        """
        Used by followup.py.

        Returns papers previously stored for this session, including a short
        summary taken from the first available chunk.
        """
        results = self.collection.get(
            where={"session_id": session_id},
            include=["metadatas", "documents"],
        )

        metadatas = results.get("metadatas", []) or []
        documents = results.get("documents", []) or []

        seen = {}

        for meta, doc in zip(metadatas, documents):
            meta = dict(meta)

            link = meta.get("link")
            if not link:
                continue

            authors_raw = meta.get("authors", "")
            meta["authors"] = authors_raw.split("|") if authors_raw else []

            if link not in seen:
                meta["summary"] = (doc or "")[:800]
                seen[link] = meta

        papers = list(seen.values())[:limit]

        return {
            "papers": papers,
        }

    def find_papers_by_title(
        self,
        titles: list[str],
        session_id: str,
    ) -> list[dict]:
        session_papers = self.get_session_papers(session_id)
        matched = []

        for requested in titles:
            req_norm = requested.strip().lower()
            best = None

            for meta in session_papers:
                title_norm = meta["title"].strip().lower()

                if req_norm in title_norm or title_norm in req_norm:
                    best = meta
                    break

            if best:
                matched.append(best)

        return matched

    def delete_paper(self, link: str, session_id: str):
        self.collection.delete(
            where={
                "$and": [
                    {"session_id": session_id},
                    {"link": link},
                ]
            }
        )

    def get_full_text_for_paper(self, link: str, session_id: str) -> str:
        results = self.collection.get(
            where={
                "$and": [
                    {"session_id": session_id},
                    {"link": link},
                ]
            }
        )

        chunks_with_idx = sorted(
            zip(results["metadatas"], results["documents"]),
            key=lambda x: x[0].get("chunk_index", 0),
        )

        return "\n".join(doc for _, doc in chunks_with_idx)


def _get_paper_embed_collection():
    global _paper_embed_collection

    if _paper_embed_collection is None:
        client = chromadb.PersistentClient(
            path=settings.CHROMA_PERSIST_DIR,
            settings=ChromaSettings(anonymized_telemetry=False),
        )

        _paper_embed_collection = client.get_or_create_collection(
            name="paper_embeddings",
            metadata={"hnsw:space": "cosine"},
        )

    return _paper_embed_collection


def cache_paper_embedding(
    paper_fingerprint: str,
    embedding: list[float],
    metadata: dict | None = None,
):
    col = _get_paper_embed_collection()

    col.upsert(
        ids=[paper_fingerprint],
        embeddings=[embedding],
        metadatas=[metadata or {}],
    )


def get_cached_paper_embedding(paper_fingerprint: str) -> list[float] | None:
    col = _get_paper_embed_collection()

    result = col.get(
        ids=[paper_fingerprint],
        include=["embeddings"],
    )

    if result and result["embeddings"] and result["embeddings"][0]:
        return result["embeddings"][0]

    return None


def batch_get_paper_embeddings(
    fingerprints: list[str],
) -> dict[str, list[float]]:
    col = _get_paper_embed_collection()

    result = col.get(
        ids=fingerprints,
        include=["embeddings"],
    )

    out = {}

    for fp, emb in zip(result["ids"], result["embeddings"]):
        if emb is not None:
            out[fp] = emb

    return out


vector_store = VectorStore()