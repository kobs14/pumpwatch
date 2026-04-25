"""Alerts-test fixtures.

Mirrors ``tests/scheduler/conftest.py``: alerts code opens its own
sessions and commits, so isolation comes from a TRUNCATE bracket
around the yield. Consolidating the now-five truncate-style fixtures
is a Session 7 cleanup item.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

_TRUNCATE_SQL = "TRUNCATE users, tokens, price_snapshots, api_call_log RESTART IDENTITY CASCADE"


@pytest_asyncio.fixture
async def alerts_sessionmaker(
    test_engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Yield a sessionmaker bound to the shared test engine, TRUNCATE-bracketed."""
    async with test_engine.begin() as conn:
        await conn.execute(text(_TRUNCATE_SQL))
    maker = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield maker
    finally:
        async with test_engine.begin() as conn:
            await conn.execute(text(_TRUNCATE_SQL))
