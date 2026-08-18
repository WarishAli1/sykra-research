from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import (
    chat,
    upload,
    followup,
    research,
    export,
    filename as filename_route,
)
from app.api.routes.studio import router as studio_router
from app.services.graph_store import graph_store

try:
    from app.services.paper_search import aclose_http_clients
except ImportError:
    async def aclose_http_clients():
        return None


Path("uploads").mkdir(exist_ok=True)
Path("exports").mkdir(exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    
    try:
        graph_store.ensure_constraints()
    except Exception as e:
        print(f"[startup] graph_store.ensure_constraints failed: {type(e).__name__}: {e}")

    yield

    try:
        await aclose_http_clients()
    except Exception as e:
        print(f"[shutdown] aclose_http_clients failed: {type(e).__name__}: {e}")


app = FastAPI(
    title="AI Research Assistant",
    lifespan=lifespan,
)

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
app.include_router(filename_route.router, prefix="/api")
app.include_router(export.router, prefix="/api")
app.include_router(studio_router, prefix="/api/studio", tags=["studio"])

app.mount("/api/uploads", StaticFiles(directory="uploads"), name="uploads")
app.mount("/exports", StaticFiles(directory="exports"), name="exports")


@app.get("/")
def root():
    return {"status": "ok"}