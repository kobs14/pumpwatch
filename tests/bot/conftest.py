"""Bot-test fixtures: TRUNCATE-on-teardown sessionmaker via the shared helper.

Bot handlers open their own sessions and commit, so we isolate by
TRUNCATING after each test rather than relying on SAVEPOINT rollback.
``truncate_on_entry=False`` preserves the legacy "cleanup only"
behaviour the bot tests historically relied on.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests._helpers.sessionmaker import BOT_TABLES, truncating_sessionmaker


@pytest_asyncio.fixture
async def bot_sessionmaker(
    test_engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Yield a sessionmaker; TRUNCATE on teardown."""
    async with truncating_sessionmaker(
        test_engine, tables=BOT_TABLES, truncate_on_entry=False
    ) as maker:
        yield maker
