"""FastAPI application entrypoint."""
import logging
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.api.v1.router import api_router
from app.db.session import init_db
from app.ws.route import router as ws_router
from app.ws.events import redis_ws_bridge

logger = logging.getLogger(__name__)


def _cors_origins() -> list[str]:
    base = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:12000",
        "http://127.0.0.1:12000",
        "http://192.168.31.130:12000",
        "http://192.168.31.130:3000",
    ]
    extra = [o.strip() for o in (settings.cors_extra_origins or "").split(",") if o.strip()]
    return [*base, *extra]


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    try:
        await redis_ws_bridge.start()
    except Exception as e:
        logger.warning("Redis WS bridge failed to start (realtime updates disabled): %s", e)
    yield
    await redis_ws_bridge.stop()


app = FastAPI(
    title="Sport Analyzator API",
    description="Table tennis events, odds, probabilities, value signals",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Логируем любое необработанное исключение и возвращаем 500. В теле всегда есть error_type и error_detail для отладки."""
    from fastapi import HTTPException
    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    tb = traceback.format_exc()
    logger.exception("Unhandled error on %s %s: %s", request.method, request.url.path, exc)
    content = {
        "detail": str(exc) if settings.debug else "Internal server error",
        "error_type": type(exc).__name__,
        "error_detail": str(exc),
    }
    if settings.debug:
        content["traceback"] = tb
    return JSONResponse(status_code=500, content=content)


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_v1_prefix)
app.include_router(ws_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
