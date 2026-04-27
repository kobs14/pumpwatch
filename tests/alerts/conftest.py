"""Alerts-test fixtures: TRUNCATE-bracketed sessionmaker via the shared helper."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests._helpers.sessionmaker import CORE_TABLES, truncating_sessionmaker


@pytest_asyncio.fixture
async def alerts_sessionmaker(
    test_engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Yield a sessionmaker bound to the shared test engine, TRUNCATE-bracketed."""
    async with truncating_sessionmaker(test_engine, tables=CORE_TABLES) as maker:
        yield maker
