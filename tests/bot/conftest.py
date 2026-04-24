"""Bot-test fixtures: sessionmaker bound to the shared test engine.

Bot handlers open their own sessions and commit — they cannot participate in
the SAVEPOINT-based per-test rollback the other repo tests use. We isolate
bot tests by TRUNCATING the tables they touch between tests instead.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


@pytest_asyncio.fixture
async def bot_sessionmaker(
    test_engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Yield a sessionmaker bound to the session-scoped test engine, then truncate."""
    maker = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield maker
    finally:
        # Cascade wipes subscriptions + alerts_sent when users/tokens go.
        async with test_engine.begin() as conn:
            await conn.execute(
                text("TRUNCATE users, tokens, price_snapshots RESTART IDENTITY CASCADE")
            )
