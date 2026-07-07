from fastapi import APIRouter
from app.models.schemas import ChatRequest, ChatResponse, PaperResult
from app.services.paper_search import search_arxiv

router = APIRouter()

@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    raw = search_arxiv(req.query)[:5]
    papers = [PaperResult(**{k: v for k, v in p.items() if k in PaperResult.model_fields}) for p in raw]
    return ChatResponse(
        answer="Agent pipeline not wired yet — this is raw search only.",
        papers=papers,
        citations=[]
    )
