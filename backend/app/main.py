"""FastAPI application."""
import logging
import traceback

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.api.v1.router import api_router
from app.db.session import init_db

logger = logging.getLogger(__name__)


def _cors_origins() -> list[str]:
    base = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:11000",
        "http://127.0.0.1:11000",
    ]
    extra = [o.strip() for o in (settings.cors_extra_origins or "").split(",") if o.strip()]
    return [*base, *extra]


app = FastAPI(
    title="PingWin API",
    description="Auth: email + Telegram, code verification",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)


@app.on_event("startup")
async def startup():
    await init_db()


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    from fastapi import HTTPException
    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    logger.exception("Unhandled error: %s", exc)
    content = {"detail": str(exc) if settings.debug else "Internal server error"}
    if settings.debug:
        content["traceback"] = traceback.format_exc()
    return JSONResponse(status_code=500, content=content)


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/health")
async def health():
    return {"status": "ok"}
