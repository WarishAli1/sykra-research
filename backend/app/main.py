from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import chat, upload, followup, compare, citation

app = FastAPI(title="AI Research Assistant")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router, prefix="/api")
app.include_router(upload.router, prefix="/api")
app.include_router(followup.router, prefix="/api")
app.include_router(compare.router, prefix="/api")
app.include_router(citation.router, prefix="/api")

@app.get("/")
def root():
    return {"status": "ok"}
