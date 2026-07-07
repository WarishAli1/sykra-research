from langchain_groq import ChatGroq
from app.config import settings

def get_llm(temperature: float = 0.2):
    return ChatGroq(
        api_key=settings.GROQ_API_KEY,
        model="llama-3.3-70b-versatile",
        temperature=temperature
    )
