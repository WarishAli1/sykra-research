from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.api.routes import chat, upload, followup, research
from app.services.graph_store import graph_store

Path("uploads").mkdir(exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    graph_store.ensure_constraints()
    yield


app = FastAPI(title="AI Research Assistant", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router, prefix="/api")
app.include_router(upload.router, prefix="/api")
app.include_router(followup.router, prefix="/api")
app.include_router(research.router, prefix="/api")

app.mount("/api/uploads", StaticFiles(directory="uploads"), name="uploads")

@app.get("/")
def root():
    return {"status": "ok"}
