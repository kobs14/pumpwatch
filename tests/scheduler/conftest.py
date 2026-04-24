"""Scheduler-test fixtures.

Mirrors ``tests/bot/conftest.py``: scheduler tasks open their own sessions
(via ``get_sessionmaker``) and commit, so per-test isolation comes from a
TRUNCATE in teardown, not the SAVEPOINT pattern used by repo tests.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

_TRUNCATE_SQL = "TRUNCATE users, tokens, price_snapshots, api_call_log RESTART IDENTITY CASCADE"


@pytest_asyncio.fixture
async def scheduler_sessionmaker(
    test_engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Yield a sessionmaker bound to the shared test engine.

    Truncate on both sides of the yield: entry so we're never downstream of
    another test file's leftover rows, and teardown so we leave the DB clean
    for the next test to use.
    """
    async with test_engine.begin() as conn:
        await conn.execute(text(_TRUNCATE_SQL))
    maker = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield maker
    finally:
        async with test_engine.begin() as conn:
            await conn.execute(text(_TRUNCATE_SQL))
