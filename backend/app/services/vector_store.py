import chromadb
from chromadb.utils import embedding_functions
from app.config import settings

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

    def add_chunks(self, ids: list[str], texts: list[str], metadatas: list[dict]):
        self.collection.add(ids=ids, documents=texts, metadatas=metadatas)

    def query(self, query_text: str, n_results: int = 5):
        return self.collection.query(query_texts=[query_text], n_results=n_results)

vector_store = VectorStore()
