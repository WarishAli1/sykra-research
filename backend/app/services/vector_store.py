import hashlib

import chromadb
from chromadb.config import Settings as ChromaSettings
from chromadb.utils import embedding_functions
from app.config import settings


from app.services.chunking import chunk_text


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

    def query_uploaded_documents(self, session_id: str, query: str, k: int = 5) -> dict:
        return self.query_session(query, session_id, n_results=k)

    def get_session_papers(self, session_id: str) -> list[dict]:
        results = self.collection.get(where={"session_id": session_id})
        seen = {}
        for meta in results.get("metadatas", []):
            meta = dict(meta)
            authors_raw = meta.get("authors", "")
            meta["authors"] = authors_raw.split("|") if authors_raw else []
            seen[meta["link"]] = meta
        return list(seen.values())

    def find_papers_by_title(self, titles: list[str], session_id: str) -> list[dict]:
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
        results = self.collection.get(where={"$and": [{"session_id": session_id}, {"link": link}]})
        chunks_with_idx = sorted(
            zip(results["metadatas"], results["documents"]),
            key=lambda x: x[0].get("chunk_index", 0)
        )
        return "\n".join(doc for _, doc in chunks_with_idx)


vector_store = VectorStore()
