"""Unit tests for ``DlqRepository``."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from pumpwatch.db.models import DlqEntry
from pumpwatch.db.repos.dlq import DlqRepository


@pytest_asyncio.fixture
async def dlq_sessionmaker(
    test_engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Truncate ``dlq_entries`` so each test starts empty."""
    async with test_engine.begin() as conn:
        await conn.execute(text("TRUNCATE dlq_entries RESTART IDENTITY"))
    yield async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)
    async with test_engine.begin() as conn:
        await conn.execute(text("TRUNCATE dlq_entries RESTART IDENTITY"))


async def test_upsert_inserts_first_failure(
    dlq_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async with dlq_sessionmaker() as session, session.begin():
        await DlqRepository(session).upsert("tok1", "boom")

    async with dlq_sessionmaker() as session:
        rows = (await session.execute(select(DlqEntry))).scalars().all()
    assert len(rows) == 1
    assert rows[0].token_address == "tok1"
    assert rows[0].error == "boom"
    assert rows[0].attempts == 1


async def test_upsert_bumps_attempts_on_conflict(
    dlq_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async with dlq_sessionmaker() as session, session.begin():
        await DlqRepository(session).upsert("tok2", "first error")
    async with dlq_sessionmaker() as session, session.begin():
        await DlqRepository(session).upsert("tok2", "second error")

    async with dlq_sessionmaker() as session:
        rows = (await session.execute(select(DlqEntry))).scalars().all()
    assert len(rows) == 1, "UNIQUE(token_address) must coalesce the second insert"
    row = rows[0]
    assert row.attempts == 2
    assert row.error == "second error"  # latest message wins
    assert row.first_seen <= row.last_seen


async def test_count_reflects_distinct_tokens(
    dlq_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async with dlq_sessionmaker() as session, session.begin():
        await DlqRepository(session).upsert("a", "x")
        await DlqRepository(session).upsert("b", "x")
        await DlqRepository(session).upsert("a", "y")  # bump, not insert

    async with dlq_sessionmaker() as session:
        count = await DlqRepository(session).count()
    assert count == 2
