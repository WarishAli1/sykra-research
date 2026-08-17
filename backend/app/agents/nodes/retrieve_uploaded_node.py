from app.agents.state import AgentState
from app.services.embeddings import embed_texts, similarity
from app.services.vector_store import vector_store

RETRIEVE_CANDIDATES = 20     
MIN_CHUNK_SIM = 0.25         
MAX_PASSES = 5              
NEIGHBOR_CHARS = 450        


def _sibling_chunks(session_id: str, link: str) -> dict[int, str]:
    """All chunks of one document, keyed by chunk_index (for section rebuild)."""
    try:
        res = vector_store.collection.get(
            where={"$and": [{"session_id": session_id}, {"link": link}]},
        )
    except Exception:
        return {}
    out = {}
    for m, d in zip(res.get("metadatas", []), res.get("documents", [])):
        try:
            out[int(m.get("chunk_index", 0))] = d
        except Exception:
            continue
    return out


def retrieve_uploaded_node(state: AgentState) -> AgentState:
    if state.get("evidence_mode") == "literature":
        return {"uploaded_context": []}

    results = vector_store.query_session(
        session_id=state["session_id"],
        query_text=state["query"],
        n_results=RETRIEVE_CANDIDATES,
    )
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    if not documents:
        return {"uploaded_context": []}

    query_vec = embed_texts([state["query"]])[0]
    doc_vecs = embed_texts(documents)
    sims = [similarity(query_vec, dv) for dv in doc_vecs]

    scored = sorted(
        (
            (doc, meta, sim)
            for doc, meta, sim in zip(documents, metadatas, sims)
            if sim >= MIN_CHUNK_SIM
        ),
        key=lambda x: x[2],
        reverse=True,
    )
    if not scored:
        best = max(zip(documents, metadatas, sims), key=lambda x: x[2])
        scored = [best]

    passages = []
    covered = set()
    for doc, meta, sim in scored:
        link = meta.get("link", "unknown")
        idx = int(meta.get("chunk_index", 0))
        window_key = (link, idx // 2)
        if window_key in covered:
            continue
        covered.add(window_key)

        siblings = _sibling_chunks(state["session_id"], link)
        prev_text = siblings.get(idx - 1, "")
        next_text = siblings.get(idx + 1, "")
        merged = (
            (prev_text[-NEIGHBOR_CHARS:] + "\n" if prev_text else "")
            + doc
            + ("\n" + next_text[:NEIGHBOR_CHARS] if next_text else "")
        )
        passages.append(
            {
                "title": meta.get("title", "Uploaded document"),
                "summary": merged,
                "link": f"user_upload://{link}",
                "source": "user_upload",
                "score": sim,
                "published": meta.get("published", None),
                "authors": [meta.get("authors", "")] if meta.get("authors") else [],
            }
        )
        if len(passages) >= MAX_PASSES:
            break

    if not passages:
        return {"uploaded_context": []}

    raw = list(state.get("raw_search_results", []))
    raw.extend(passages)
    return {
        "raw_search_results": raw,
        "uploaded_context": passages,
    }