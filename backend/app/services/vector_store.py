import hashlib

import chromadb
from chromadb.utils import embedding_functions
from app.config import settings
from app.services.chunking import chunk_text


class VectorStore:
    def __init__(self):
        self.client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
        self.embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=settings.EMBEDDING_MODEL
        )
        self.collection = self.client.get_or_create_collection(
            name="papers",
            embedding_function=self.embed_fn
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

        ids = [self._chunk_id(paper["link"], i) for i in range(len(chunks))]
        metadatas = [
            {
                "session_id": session_id,
                "title": paper["title"],
                "link": paper["link"],
                "source": paper.get("source", "unknown"),
                "paper_type": paper.get("paper_type", "application"),
                "published": paper.get("published", ""),
                "chunk_index": i,
            }
            for i in range(len(chunks))
        ]

        self.collection.upsert(ids=ids, documents=chunks, metadatas=metadatas)

    def query_session(self, query_text: str, session_id: str, n_results: int = 5) -> dict:
        return self.collection.query(
            query_texts=[query_text],
            n_results=n_results,
            where={"session_id": session_id},
        )

    def get_session_papers(self, session_id: str) -> list[dict]:
        results = self.collection.get(where={"session_id": session_id})
        seen = {}
        for meta in results.get("metadatas", []):
            seen[meta["link"]] = meta
        return list(seen.values())


vector_store = VectorStore()
