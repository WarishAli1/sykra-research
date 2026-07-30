from app.agents.state import AgentState
from app.services.embeddings import embed_texts, similarity
from app.services.vector_store import vector_store


def retrieve_uploaded_node(state: AgentState) -> AgentState:
    if state.get("evidence_mode") == "literature":
        return {**state, "uploaded_context": []}

    results = vector_store.query_session(
        session_id=state["session_id"],
        query_text=state["query"],
        n_results=12,
    )

    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]

    if not documents:
        return {**state, "uploaded_context": []}

    query_vec = embed_texts([state["query"]])[0]
    doc_vecs = embed_texts(documents)
    sims = [similarity(query_vec, dv) for dv in doc_vecs]

    uploaded_papers = []
    for doc, meta, sim in zip(documents, metadatas, sims):
        uploaded_papers.append({
            "title": meta.get("title", "Uploaded document"),
            "summary": doc[:2000],
            "link": f"user_upload://{meta.get('link', 'unknown')}",
            "source": "user_upload",
            "score": sim,
            "published": meta.get("published", None),
            "authors": [meta.get("authors", "")] if meta.get("authors") else [],
        })

    raw = list(state.get("raw_search_results", []))
    raw.extend(uploaded_papers)

    return {
        **state,
        "raw_search_results": raw,
        "uploaded_context": uploaded_papers,
    }