from app.services.embeddings import embed_texts, similarity

SIMILARITY_THRESHOLD = 0.55
MAX_CLUSTERS = 4
MAX_PAPERS_PER_CLUSTER = 3


def _even_chunks(papers: list[dict], n_chunks: int) -> list[list[dict]]:
    chunk_size = max(1, len(papers) // n_chunks)
    chunks = [papers[i:i+chunk_size] for i in range(0, len(papers), chunk_size)]
    if len(chunks) > n_chunks and len(chunks[-1]) < chunk_size // 2:
        chunks[-2].extend(chunks[-1])
        chunks.pop()
    return chunks


def _greedy_cluster(papers: list[dict], max_clusters: int) -> list[list[int]]:
    texts = [
        p.get("summary", "")[:400] or p.get("title", "") or "untitled paper"
        for p in papers
    ]
    vecs = embed_texts(texts)

    clusters: list[list[int]] = []
    cluster_centroids: list[list[float]] = []

    for i, vec in enumerate(vecs):
        if not clusters:
            clusters.append([i])
            cluster_centroids.append(vec)
            continue

        sims = [similarity(vec, c) for c in cluster_centroids]
        candidate_order = sorted(range(len(sims)), key=lambda idx: sims[idx], reverse=True)

        placed = False
        for cand in candidate_order:
            if sims[cand] >= SIMILARITY_THRESHOLD and len(clusters[cand]) < MAX_PAPERS_PER_CLUSTER:
                clusters[cand].append(i)
                n = len(clusters[cand])
                cluster_centroids[cand] = [
                    (c * (n - 1) + v) / n for c, v in zip(cluster_centroids[cand], vec)
                ]
                placed = True
                break

        if not placed:
            if len(clusters) < max_clusters:
                clusters.append([i])
                cluster_centroids.append(vec)
            else:
                least_full = min(range(len(clusters)), key=lambda idx: len(clusters[idx]))
                clusters[least_full].append(i)

    return clusters


def cluster_papers(papers: list[dict], max_clusters: int = MAX_CLUSTERS) -> list[list[dict]]:
    if not papers:
        return []
    if len(papers) <= max_clusters:
        return [[p] for p in papers]

    raw = _greedy_cluster(papers, max_clusters)
    non_empty = [c for c in raw if c]

    if len(non_empty) <= 1:
        return _even_chunks(papers, max_clusters)

    return [[papers[i] for i in cluster] for cluster in non_empty]
