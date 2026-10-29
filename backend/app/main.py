from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.routes import (
    chat,
    auth,
    account,
    chats,
    library,
    upload,
    followup,
    research,
    export,
    filename as filename_route,
    sessions,
    avatar,
)
from app.config import settings
from app.db.database import create_tables
from app.auth import get_current_user
from app.api.routes.studio import router as studio_router
from app.api.routes.report import router as report_router
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
    create_tables()
    
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
app.state.limiter = Limiter(key_func=get_remote_address)
app.add_exception_handler(RateLimitExceeded, lambda request, exc: JSONResponse({"detail": "Too many requests."}, status_code=429))
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[item.strip() for item in settings.TRUSTED_ORIGINS.split(",") if item.strip()],
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Requested-With"],
    allow_credentials=True,
)


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    if settings.ENVIRONMENT == "production" and request.url.scheme != "https":
        secure_url = request.url.replace(scheme="https")
        return RedirectResponse(str(secure_url), status_code=307)
    origin = request.headers.get("origin")
    trusted = {item.strip() for item in settings.TRUSTED_ORIGINS.split(",") if item.strip()}
    if origin and origin not in trusted:
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Origin not allowed."}, status_code=403)
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.headers.get("content-length"):
        if int(request.headers["content-length"]) > 30 * 1024 * 1024:
            return JSONResponse({"detail": "Request too large."}, status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'; object-src 'none'"
    if settings.ENVIRONMENT == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

app.include_router(auth.router, prefix="/api")
app.include_router(account.router, prefix="/api")
app.include_router(chats.router, prefix="/api")
app.include_router(sessions.router, prefix="/api")
app.include_router(avatar.router, prefix="/api")
app.include_router(library.router, prefix="/api")
protected = [Depends(get_current_user)]
app.include_router(chat.router, prefix="/api", dependencies=protected)
app.include_router(upload.router, prefix="/api", dependencies=protected)
app.include_router(followup.router, prefix="/api", dependencies=protected)
app.include_router(research.router, prefix="/api", dependencies=protected)
app.include_router(filename_route.router, prefix="/api", dependencies=protected)
app.include_router(export.router, prefix="/api", dependencies=protected)
app.include_router(studio_router, prefix="/api/studio", tags=["studio"], dependencies=protected)
app.include_router(report_router, prefix="/api", dependencies=protected)
app.mount("/exports", StaticFiles(directory="exports"), name="exports")


@app.get("/")
def root():
    return {"status": "ok"}