"""ML database: sync engine для обучения и batch-скриптов."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.config import settings


def get_ml_engine():
    workers = getattr(settings, "ml_backfill_workers", 1)
    pool_size = max(4, min(10, workers + 2))
    max_overflow = max(4, min(10, workers))
    return create_engine(
        settings.database_url_ml,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
    )


_ml_engine = None
_ml_session_factory = None


def get_ml_session() -> Session:
    global _ml_engine, _ml_session_factory
    if _ml_engine is None:
        _ml_engine = get_ml_engine()
        _ml_session_factory = sessionmaker(_ml_engine, autocommit=False, autoflush=False)
    return _ml_session_factory()
