"""End-to-end: worker fetch → Postgres snapshot + real Redis cache + publish.

Exercises the production Redis path that fakeredis can't fully validate
(connection pool behaviour across ``asyncio.run`` boundaries, server-
provided SUBSCRIBE confirmation semantics, binary-safe publish). Skips
cleanly if no Redis is reachable at ``REDIS_URL``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from pumpwatch.cache.redis_client import PRICE_UPDATED_CHANNEL, cache_key_for
from pumpwatch.config import get_settings
from pumpwatch.db.enums import Priority
from pumpwatch.db.models import PriceSnapshot, Subscription, Token, User
from pumpwatch.scheduler import tasks as scheduler_tasks
from pumpwatch.sources.base import TokenSnapshot
from pumpwatch.sources.fake import FakePriceDataSource
from tests.celery_helpers import eager_celery  # noqa: F401  (fixture import)

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("eager_celery")]

_TRUNCATE_SQL = "TRUNCATE users, tokens, price_snapshots, api_call_log RESTART IDENTITY CASCADE"


@pytest_asyncio.fixture
async def scheduler_sessionmaker(
    test_engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Local copy of the scheduler-package fixture — we're outside that package."""
    async with test_engine.begin() as conn:
        await conn.execute(text(_TRUNCATE_SQL))
    maker = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield maker
    finally:
        async with test_engine.begin() as conn:
            await conn.execute(text(_TRUNCATE_SQL))


def _redis_reachable(url: str) -> bool:
    try:
        import redis
    except ImportError:  # pragma: no cover — redis is a runtime dep now
        return False
    try:
        client = redis.Redis.from_url(url, socket_connect_timeout=0.5)
        return bool(client.ping())
    except Exception:
        return False


_ADDR = "tokREALR"


async def _subscriber_task(
    redis_url: str,
    ready: asyncio.Event,
    received: list[dict[str, Any]],
    stop: asyncio.Event,
) -> None:
    client = aioredis.from_url(redis_url)
    pubsub = client.pubsub()
    try:
        await pubsub.subscribe(PRICE_UPDATED_CHANNEL)
        # Drain the subscribe confirmation.
        for _ in range(10):
            msg = await pubsub.get_message(ignore_subscribe_messages=False, timeout=0.1)
            if msg and msg.get("type") == "subscribe":
                break
        ready.set()
        while not stop.is_set():
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
            if msg is None:
                continue
            data = msg["data"]
            if isinstance(data, bytes):
                received.append(json.loads(data))
                if received:
                    return
    finally:
        await pubsub.aclose()  # type: ignore[no-untyped-call]
        await client.aclose()


async def test_fetch_token_round_trips_through_real_redis(
    scheduler_sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_url = str(get_settings().REDIS_URL)
    if not _redis_reachable(redis_url):
        pytest.skip(f"redis at {redis_url} not reachable")

    async with scheduler_sessionmaker() as session, session.begin():
        user = User(telegram_id=501, chat_id=501, telegram_username="rr")
        session.add(user)
        await session.flush()
        session.add(Token(address=_ADDR, symbol="RR", name="RR"))
        await session.flush()
        session.add(
            Subscription(
                user_id=user.id,
                token_address=_ADDR,
                growth_threshold_pct=Decimal("10"),
                stoploss_threshold_pct=Decimal("10"),
                priority=Priority.HIGH,
            )
        )

    snap = TokenSnapshot(
        address=_ADDR,
        symbol="RR",
        name="RR",
        market_cap_usd=Decimal("4200"),
        price_usd=None,
        volume_5m_usd=Decimal("77"),
        liquidity_usd=None,
        holder_count=None,
        source="fake",
        fetched_at=datetime(2026, 4, 24, 12, 0, tzinfo=UTC),
    )
    fake = FakePriceDataSource({_ADDR: [snap]})
    monkeypatch.setattr(scheduler_tasks, "_build_source", lambda _sm: fake)
    monkeypatch.setattr(scheduler_tasks, "get_sessionmaker", lambda: scheduler_sessionmaker)

    ready = asyncio.Event()
    stop = asyncio.Event()
    received: list[dict[str, Any]] = []
    sub_task = asyncio.create_task(_subscriber_task(redis_url, ready, received, stop))
    try:
        # Wait for SUBSCRIBE confirmation — publishes before this would
        # land in a dropped message (pub-sub has no replay).
        await asyncio.wait_for(ready.wait(), timeout=2.0)

        result = await asyncio.to_thread(lambda: scheduler_tasks.fetch_token.delay(_ADDR).get())
        assert result == {"address": _ADDR, "fetched": True, "tier": "high"}

        # Let the subscriber drain the published message.
        try:
            await asyncio.wait_for(sub_task, timeout=2.0)
        except TimeoutError:  # pragma: no cover — fires only if publish is dropped
            stop.set()
            raise
    finally:
        stop.set()
        if not sub_task.done():
            sub_task.cancel()
            try:
                await sub_task
            except (asyncio.CancelledError, Exception):
                pass

    assert received, "expected at least one pw:price.updated message"
    assert received[0]["address"] == _ADDR
    assert received[0]["tier"] == "high"
    assert received[0]["cache_key"] == cache_key_for(_ADDR)

    async with scheduler_sessionmaker() as session:
        rows = (
            (
                await session.execute(
                    select(PriceSnapshot).where(PriceSnapshot.token_address == _ADDR)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1

    # Read-back through a fresh client (mirrors Session 6 / CLI usage).
    reader = aioredis.from_url(redis_url)
    try:
        raw = await reader.get(cache_key_for(_ADDR))
        assert raw is not None
        cached = json.loads(raw)
        assert cached["address"] == _ADDR
        assert cached["tier"] == "high"
        assert cached["market_cap_usd"] == "4200"
    finally:
        # Clean our key so re-runs start from zero.
        await reader.delete(cache_key_for(_ADDR))
        await reader.aclose()
