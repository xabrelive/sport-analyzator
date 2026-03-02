"""Database session and engine."""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings
from app.db.base import Base

engine = create_async_engine(
    settings.async_database_url,
    echo=settings.debug,
    pool_pre_ping=True,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


def create_worker_engine_and_session():
    """Create a new async engine and session maker for use inside a single asyncio.run() (e.g. Celery task).
    Use this in worker async entry points so the engine is used in the same event loop. Caller must await engine.dispose() when done."""
    eng = create_async_engine(
        settings.async_database_url,
        echo=settings.debug,
        pool_pre_ping=True,
    )
    maker = async_sessionmaker(
        eng,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    return eng, maker


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
