"""Shared test fixtures.

The ``os.environ.setdefault`` calls still run before any ``pumpwatch.*`` import
so pydantic-settings has the values it needs when ``Settings()`` is first
constructed. As of Session 3, ``pumpwatch.db.session`` is lazy-init — tests
use their own ``NullPool`` engine (see ``test_engine``) and never touch the
module-level singletons.
"""

from __future__ import annotations

import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://pumpwatch:pumpwatch@localhost:5432/pumpwatch_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token-not-real")
os.environ.setdefault("ENVIRONMENT", "test")

# Now it's safe to import pumpwatch modules.
import asyncio
from collections.abc import AsyncIterator
from urllib.parse import urlparse, urlunparse

import asyncpg
import pytest_asyncio
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from pumpwatch.config import get_settings
from pumpwatch.db.session import _reset_for_tests

# Clear any cached Settings() captured before env vars were set above, and
# drop any db-session singleton a previous test process may have cached.
get_settings.cache_clear()
_reset_for_tests()


def _admin_dsn(test_url: str) -> tuple[str, str]:
    """Return ``(admin_asyncpg_dsn, test_db_name)`` for the test database URL.

    asyncpg expects a ``postgresql://`` DSN (no ``+asyncpg``) and the admin
    connection must hit an always-present DB (``postgres``) since you cannot
    drop a DB you're currently connected to.
    """
    parsed = urlparse(test_url.replace("postgresql+asyncpg", "postgresql"))
    test_db = parsed.path.lstrip("/")
    admin = parsed._replace(path="/postgres")
    return urlunparse(admin), test_db


def _run_migrations(sqlalchemy_url: str) -> None:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", sqlalchemy_url)
    command.upgrade(cfg, "head")


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _test_database() -> AsyncIterator[None]:
    """Create a clean ``pumpwatch_test`` database, migrate it, drop on teardown."""
    settings = get_settings()
    test_url = str(settings.DATABASE_URL)
    admin_dsn, test_db = _admin_dsn(test_url)

    admin = await asyncpg.connect(admin_dsn)
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{test_db}" WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE "{test_db}"')
    finally:
        await admin.close()

    # alembic/env.py uses asyncio.run() internally, which conflicts with the
    # pytest-asyncio event loop we're already running in. Run it in a thread.
    await asyncio.to_thread(_run_migrations, test_url)
    yield

    admin = await asyncpg.connect(admin_dsn)
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{test_db}" WITH (FORCE)')
    finally:
        await admin.close()


@pytest_asyncio.fixture(scope="session")
async def test_engine() -> AsyncIterator[AsyncEngine]:
    """Session-scoped async engine bound to the test database."""
    settings = get_settings()
    engine = create_async_engine(str(settings.DATABASE_URL), poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Function-scoped session wrapped in an outer transaction.

    The outer transaction is rolled back at teardown, so each test sees a
    clean database state regardless of what it wrote.
    """
    async with test_engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(
            bind=conn,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()
