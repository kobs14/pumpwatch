"""Shared truncate-style sessionmaker helper.

Most service-package tests open their own sessions and commit, so the
SAVEPOINT-rollback pattern from repo tests doesn't isolate them. The
TRUNCATE-bracketed helper here is the common shape used by the bot,
scheduler, alerts, and integration tests.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


async def _truncate(engine: AsyncEngine, tables: list[str]) -> None:
    sql = f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"
    async with engine.begin() as conn:
        await conn.execute(text(sql))


@asynccontextmanager
async def truncating_sessionmaker(
    engine: AsyncEngine,
    *,
    tables: list[str],
    truncate_on_entry: bool = True,
    truncate_on_exit: bool = True,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Yield a sessionmaker bracketed by TRUNCATE.

    ``CASCADE`` so dependent tables (e.g. subscriptions, alerts_sent)
    get cleaned via foreign-key cascades — list only the parents.

    The ``truncate_on_entry=False`` variant matches the legacy
    ``tests/bot/conftest.py`` shape (cleanup only) and is preserved
    here so callers can opt out without bypassing the helper.
    """
    if truncate_on_entry:
        await _truncate(engine, tables)
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield maker
    finally:
        if truncate_on_exit:
            await _truncate(engine, tables)


# Common table sets so callers don't drift apart again.
CORE_TABLES = ["users", "tokens", "price_snapshots", "api_call_log", "dlq_entries"]
BOT_TABLES = ["users", "tokens", "price_snapshots"]
