import hashlib
from typing import Optional, List
from app.services.vector_store import (
    cache_paper_embedding,
    get_cached_paper_embedding,
    batch_get_paper_embeddings,
)

def _fingerprint(paper: dict) -> str:
    title = paper.get("title", "").strip().lower()
    first_author = (paper.get("authors", [""])[0] if paper.get("authors") else "").lower()
    year = paper.get("published", "")[:4]
    raw = f"{title}|{first_author}|{year}"
    return hashlib.sha256(raw.encode()).hexdigest()

def get_cached_embedding(paper: dict) -> Optional[List[float]]:
    return get_cached_paper_embedding(_fingerprint(paper))

def cache_embedding(paper: dict, embedding: List[float]):
    cache_paper_embedding(_fingerprint(paper), embedding, {"title": paper.get("title")})

def batch_get_or_compute(papers: list[dict], embed_fn) -> list[tuple[dict, list[float]]]:
    """
    For a list of papers, retrieve cached embeddings or compute missing ones.
    Returns list of (paper, embedding_vector) in the same order.
    """
    fps = [_fingerprint(p) for p in papers]

    existing = batch_get_paper_embeddings(fps) 

    need_compute_indices = []
    need_compute_papers = []
    for i, (p, fp) in enumerate(zip(papers, fps)):
        if fp not in existing:
            need_compute_indices.append(i)
            need_compute_papers.append(p)

    if need_compute_papers:
        abstracts = [p.get("summary", "")[:300] or p["title"] for p in need_compute_papers]
        new_vecs = embed_fn(abstracts) 
        for idx, vec, paper in zip(need_compute_indices, new_vecs, need_compute_papers):
            cache_embedding(paper, vec)
            existing[_fingerprint(paper)] = vec 

    return [(p, existing[fp]) for p, fp in zip(papers, fps)]