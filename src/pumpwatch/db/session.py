"""Async database engine and session management.

The engine and sessionmaker are constructed lazily on first call so that
importing this module does not bind to a live Postgres connection. This lets
tests swap ``DATABASE_URL`` after import, and lets the bot/worker entrypoints
fail loudly on their own terms if the env is misconfigured.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from pumpwatch.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the process-wide async engine, constructing it on first call."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            str(settings.DATABASE_URL),
            pool_size=10,
            max_overflow=5,
            pool_pre_ping=True,
            echo=settings.ENVIRONMENT == "dev" and settings.LOG_LEVEL.upper() == "DEBUG",
        )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide async sessionmaker, constructing it on first call."""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            class_=AsyncSession,
        )
    return _sessionmaker


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session from the lazy sessionmaker."""
    async with get_sessionmaker()() as session:
        yield session


async def dispose_engine() -> None:
    """Dispose the engine if constructed. Safe to call multiple times."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


def _reset_for_tests() -> None:
    """Drop the cached singletons so tests can rebind to a fresh engine.

    Does not dispose the previous engine (callers own lifecycle). Use only in
    test setup/teardown; not part of the public API.
    """
    global _engine, _sessionmaker
    _engine = None
    _sessionmaker = None
