from fastapi import APIRouter, HTTPException
from langchain_core.messages import SystemMessage, HumanMessage

from app.models.schemas import FollowupRequest, FollowupResponse
from app.services.vector_store import vector_store
from app.services.llm_client import get_llm
from app.services.structured_answer import get_followup_answer
from app.services.embeddings import embed_texts, similarity
from app.services.reference_builder import build_references, format_reference_block

router = APIRouter()


@router.post("/followup", response_model=FollowupResponse)
def followup(req: FollowupRequest):
    results = vector_store.query_session(req.question, req.session_id, n_results=5)
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]

    if not documents:
        raise HTTPException(
            status_code=404,
            detail="This session doesn't have any papers or documents yet. Ask a research question or "
                    "upload a PDF first, then follow-up questions will be able to draw on that context."
        )

    context_block = "\n\n".join(
        f"[{meta['title']}]: {doc}"
        for doc, meta in zip(documents, metadatas)
    )

    depth_instruction = (
        "Write a full, detailed, well-structured explanation. This is researched mode."
        if req.response_mode == "researched"
        else "Keep the answer concise."
    )

    llm = get_llm(temperature=0.0)

    prompt = f"""Answer using ONLY the conversation context below.

If it lacks enough information, say so honestly.

{depth_instruction}

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

    paper_dicts = [
        {
            "title": meta["title"],
            "link": meta.get("link", ""),
            "source": meta.get("source", "unknown"),
            "authors": meta.get("authors", "").split("|") if meta.get("authors") else [],
            "published": meta.get("published") or None,
        }
        for meta in metadatas
    ]
    references = build_references(paper_dicts)

    answer_text = result.answer
    if req.response_mode == "researched" and references:
        answer_text += "\n\n---\n\n**References**\n\n" + format_reference_block(references)

    return FollowupResponse(answer=answer_text, sources=result.sources_used, references=references)