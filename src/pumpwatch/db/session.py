"""Async database engine and session management."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pumpwatch.config import get_settings

_settings = get_settings()

engine = create_async_engine(
    str(_settings.DATABASE_URL),
    pool_size=10,
    max_overflow=5,
    pool_pre_ping=True,
    echo=_settings.ENVIRONMENT == "dev" and _settings.LOG_LEVEL.upper() == "DEBUG",
)

async_session_factory = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session."""
    async with async_session_factory() as session:
        yield session
