"""FastAPI application."""
import logging
import sys
import traceback
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.api.v1.router import api_router
from app.db.session import init_db
from app.db.migrations import run_migrations as run_alembic_migrations

# Путь к корню backend (для alembic.ini)
BACKEND_ROOT = Path(__file__).resolve().parent.parent

# Чтобы логи приложения (SMTP, отправка писем) были видны в docker logs
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s [%(name)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def _run_migrations() -> None:
    """Запуск Alembic миграций до старта приложения."""
    try:
        run_alembic_migrations()
        logger.info("Alembic: миграции применены (upgrade head)")
    except Exception as e:  # noqa: BLE001
        logger.exception("Alembic: ошибка при применении миграций: %s", e)
        raise


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
    _run_migrations()
    await init_db()
    if settings.smtp_host and settings.smtp_from_email:
        logger.info(
            "SMTP настроен: host=%s port=%s from=%s (SSL=%s)",
            settings.smtp_host,
            settings.smtp_port,
            settings.smtp_from_email,
            settings.smtp_use_ssl or settings.smtp_port == 465,
        )
    else:
        logger.warning(
            "SMTP не настроен (smtp_host=%s, smtp_from_email=%s). Письма с кодами не будут отправляться.",
            settings.smtp_host or "(пусто)",
            settings.smtp_from_email or "(пусто)",
        )

    # Запускаем фоновые воркеры только если run_background_workers=True (отдельный tt_workers при масштабировании).
    if not settings.run_background_workers:
        logger.info("API-only режим: фоновые воркеры отключены (run_background_workers=false)")
    else:
        try:
            from app.worker.table_tennis_line import start_pipeline

            if (settings.betsapi_token or "").strip():
                await start_pipeline()
            else:
                logger.info("BetsAPI: betsapi_token пуст — опрос линии не запускаем.")
        except Exception as e:  # noqa: BLE001
            logger.warning("Не удалось запустить фоновый опрос BetsAPI: %s", e)


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
