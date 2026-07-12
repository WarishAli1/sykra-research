from fastapi import APIRouter, HTTPException
from langchain_core.messages import SystemMessage, HumanMessage

from app.models.schemas import CompareRequest, CompareResponse, PaperComparisonOut, ComparisonAspectOut
from app.services.vector_store import vector_store
from app.services.llm_client import get_llm
from app.agents.schemas import PaperComparison
from app.services.structured_answer import get_structured_with_fallback

router = APIRouter()

DEFAULT_ASPECTS = ["Methodology", "Dataset/Setting", "Key Findings", "Limitations"]


@router.post("/compare", response_model=CompareResponse)
def compare(req: CompareRequest):
    matched = vector_store.find_papers_by_title(req.paper_titles, req.session_id)

    if len(matched) < 2:
        raise HTTPException(
            status_code=404,
            detail=f"Only found {len(matched)} of the {len(req.paper_titles)} requested papers in this session. "
                   f"Ask about them in /chat or /followup first so they're stored."
        )

    paper_texts = {}
    for meta in matched:
        full_text = vector_store.get_full_text_for_paper(meta["link"], req.session_id)
        paper_texts[meta["title"]] = full_text[:3000]

    aspects = req.aspects or DEFAULT_ASPECTS
    paper_block = "\n\n".join(
        f"[Paper: {title}]\n{text}" for title, text in paper_texts.items()
    )

    llm = get_llm(temperature=0)
    prompt = f"""Compare these {len(matched)} papers across the following aspects: {aspects}.

For each aspect, give a value for EACH paper (using its exact title as the key).
Keep each value to 1-2 sentences — concise, not full paragraphs.
Then give a brief overall summary of the most important differences.
Only make claims that are directly supported by the paper content below — do not
invent comparisons the text doesn't support.

Papers:
{paper_block}
"""
    messages = [
        SystemMessage(content="Respond with ONLY a function call to PaperComparison. No text before or after."),
        HumanMessage(content=prompt),
    ]

    result: PaperComparison = get_structured_with_fallback(
        llm, messages, PaperComparison,
        fallback_factory=lambda: PaperComparison(
            aspects=[], overview="Comparison could not be generated due to a processing error.",
            recommendation=None
        )
    )

    return CompareResponse(
        comparison=PaperComparisonOut(
            aspects=[ComparisonAspectOut(aspect=a.aspect, paper_values=a.paper_values) for a in result.aspects],
            overview=result.overview,
            recommendation=result.recommendation,
            papers_compared=list(paper_texts.keys()),
        )
    )
