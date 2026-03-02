"""FastAPI application entrypoint."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.v1.router import api_router
from app.db.session import init_db
from app.ws.route import router as ws_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    # shutdown: close pools etc. if needed


app = FastAPI(
    title="Sport Analyzator API",
    description="Table tennis events, odds, probabilities, value signals",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_v1_prefix)
app.include_router(ws_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
