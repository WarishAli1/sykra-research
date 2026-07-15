from fastapi import APIRouter, HTTPException
from langchain_core.messages import SystemMessage, HumanMessage

from app.models.schemas import FollowupRequest, FollowupResponse
from app.services.vector_store import vector_store
from app.services.llm_client import get_llm
from app.services.structured_answer import get_followup_answer
from app.services.embeddings import embed_texts, similarity

router = APIRouter()


@router.post("/followup", response_model=FollowupResponse)
def followup(req: FollowupRequest):
    results = vector_store.query_session(req.question, req.session_id, n_results=5)
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]

    if not documents:
        raise HTTPException(
            status_code=404,
            detail="No documents found for this session. Ask a question via /api/chat first."
        )

    context_block = "\n\n".join(
        f"[{meta['title']}]: {doc}"
        for doc, meta in zip(documents, metadatas)
    )

    llm = get_llm(temperature=0.0)

    prompt = f"""Answer using ONLY the conversation context below.

If it lacks enough information, say so honestly.

Context:
{context_block}

Follow-up: {req.question}
"""
    messages = [
        SystemMessage(content="You MUST respond with valid JSON only. Never quote the excerpts. Never reproduce the document. Use the FollowupAnswer function."),
        HumanMessage(content=prompt),
    ]

    fallback_sources = list({meta["title"] for meta in metadatas})
    result = get_followup_answer(llm, messages, req.question, context_block, fallback_sources)

    return FollowupResponse(answer=result.answer, sources=result.sources_used)
