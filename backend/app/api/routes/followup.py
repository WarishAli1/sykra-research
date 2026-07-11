import hashlib
import time

from fastapi import APIRouter, HTTPException
from langchain_core.messages import SystemMessage, HumanMessage

from app.models.schemas import FollowupRequest, FollowupResponse
from app.services.vector_store import vector_store
from app.services.llm_client import get_llm
from app.services.structured_answer import get_followup_answer

router = APIRouter()

_followup_cache: dict[str, tuple[float, FollowupResponse]] = {}
CACHE_TTL = 300


def _followup_cache_key(session_id: str, question: str) -> str:
    return hashlib.sha256(f"{session_id}:{question.lower().strip()}".encode()).hexdigest()


@router.post("/followup", response_model=FollowupResponse)
def followup(req: FollowupRequest):
    cache_key = _followup_cache_key(req.session_id, req.question)
    cached = _followup_cache.get(cache_key)
    if cached and (time.time() - cached[0]) < CACHE_TTL:
        print(f"[followup] cache hit for {cache_key[:12]}")
        return cached[1]

    results = vector_store.query_session(req.question, req.session_id, n_results=5)
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]

    if not documents:
        raise HTTPException(status_code=404, detail="No stored papers found for this session. Ask a question in /chat first.")

    context_block = "\n\n".join(f"[{meta['title']}]: {doc}" for doc, meta in zip(documents, metadatas))
    llm = get_llm(temperature=0.2)

    prompt = f"""Answer the follow-up question using ONLY the retrieved excerpts below,
which come from papers already discussed in this session.

If the excerpts don't actually contain enough information to answer, set grounded=false
and say so honestly in the answer field rather than guessing.

Question: {req.question}

Retrieved excerpts:
{context_block}
"""
    messages = [
        SystemMessage(content="Respond with ONLY a function call to FollowupAnswer. Do not include any text, explanation, or preamble before or after the function call."),
        HumanMessage(content=prompt),
    ]

    fallback_sources = [m["title"] for m in metadatas]
    result = get_followup_answer(llm, messages, req.question, context_block, fallback_sources)

    response = FollowupResponse(answer=result.answer, sources=result.sources_used)
    _followup_cache[cache_key] = (time.time(), response)
    return response
