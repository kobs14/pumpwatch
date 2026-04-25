"""End-to-end alert engine path against a real Redis.

Subscribes via the alert-engine ``run`` loop, publishes a synthetic
``pw:price.updated`` event over a real Redis, and asserts a row lands
in ``alerts_sent`` with a faked ``TelegramDispatcher`` capturing the
send. Skips cleanly if no Redis is reachable at ``REDIS_URL``.

Mirrors the SUBSCRIBE-confirmation drain + ready/stop event template
from ``test_worker_price_ingestion_real_redis.py``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from pumpwatch.alerts.subscriber import run as run_subscriber
from pumpwatch.cache.redis_client import PRICE_UPDATED_CHANNEL, cache_key_for
from pumpwatch.config import get_settings
from pumpwatch.db.enums import AlertType, Priority
from pumpwatch.db.models import AlertSent, Subscription, Token, User

pytestmark = [pytest.mark.integration]

_TRUNCATE_SQL = "TRUNCATE users, tokens, price_snapshots, api_call_log RESTART IDENTITY CASCADE"
_ADDR = "tokALERT1"


@pytest_asyncio.fixture
async def alerts_sessionmaker(
    test_engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
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


class _RecordingDispatcher:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []
        self.received = asyncio.Event()

    async def send_alert(self, chat_id: int, text: str) -> None:
        self.calls.append((chat_id, text))
        self.received.set()


async def test_alerts_loop_round_trips_through_real_redis(
    alerts_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    redis_url = str(get_settings().REDIS_URL)
    if not _redis_reachable(redis_url):
        pytest.skip(f"redis at {redis_url} not reachable")

    async with alerts_sessionmaker() as s, s.begin():
        u = User(telegram_id=901, chat_id=901, telegram_username="ar")
        s.add(u)
        await s.flush()
        s.add(Token(address=_ADDR, symbol="AR", name="AR"))
        await s.flush()
        sub = Subscription(
            user_id=u.id,
            token_address=_ADDR,
            growth_threshold_pct=Decimal("10"),
            stoploss_threshold_pct=Decimal("10"),
            warning_buffer_pct=Decimal("2"),
            volume_spike_k=Decimal("3"),
            baseline_market_cap=Decimal("100"),
            priority=Priority.HIGH,
        )
        s.add(sub)

    # Clean any dedup keys left behind by a previous run of this test;
    # ``alerts_sessionmaker`` resets the DB but Redis keeps state.
    cleaner = aioredis.from_url(redis_url)
    try:
        async for raw_key in cleaner.scan_iter(match=f"pw:alert:*:{_ADDR}:*"):
            await cleaner.delete(raw_key)
    finally:
        await cleaner.aclose()

    redis_client = aioredis.from_url(redis_url)
    dispatcher = _RecordingDispatcher()
    stop_event = asyncio.Event()

    sub_task = asyncio.create_task(
        run_subscriber(
            alerts_sessionmaker,
            redis_client,
            dispatcher,  # type: ignore[arg-type]
            stop_event,
        )
    )

    try:
        # Wait for SUBSCRIBE confirmation by polling for "ready" log via a
        # short delay — the loop logs "alerts.subscriber.ready" once the
        # subscribe frame is drained. Then publish.
        await asyncio.sleep(0.3)

        publisher = aioredis.from_url(redis_url)
        try:
            payload = {
                "address": _ADDR,
                "ts": datetime(2026, 4, 25, 12, 0, tzinfo=UTC).isoformat(),
                "source": "fake",
                "tier": Priority.HIGH.value,
                "market_cap_usd": "115",
                "price_usd": "1.0",
                "volume_5m_usd": "100",
                "liquidity_usd": "0",
                "holder_count": 1,
                "cache_key": cache_key_for(_ADDR),
            }
            await publisher.publish(PRICE_UPDATED_CHANNEL, json.dumps(payload).encode())
        finally:
            await publisher.aclose()

        # Wait for the dispatcher to record the call.
        try:
            await asyncio.wait_for(dispatcher.received.wait(), timeout=3.0)
        except TimeoutError:  # pragma: no cover — fires only on regression
            pytest.fail("dispatcher did not receive the alert in time")

    finally:
        stop_event.set()
        try:
            await asyncio.wait_for(sub_task, timeout=2.0)
        except (TimeoutError, asyncio.CancelledError):
            sub_task.cancel()
            try:
                await sub_task
            except (asyncio.CancelledError, Exception):
                pass
        await redis_client.aclose()

    assert dispatcher.calls and dispatcher.calls[0][0] == 901

    async with alerts_sessionmaker() as s:
        rows = (
            (await s.execute(select(AlertSent).where(AlertSent.subscription_id != 0)))
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].alert_type == AlertType.GROWTH_HIT.value
        assert rows[0].delivered is True
