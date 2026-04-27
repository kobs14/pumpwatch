"""End-to-end tests for the scheduler Celery tasks (eager mode + test DB).

The tasks themselves wrap their async bodies in ``asyncio.run``, which
cannot be called from inside pytest-asyncio's event loop. We hop each
``.delay()`` call onto a worker thread via ``asyncio.to_thread``,
mirroring the pattern ``tests/conftest.py`` uses for Alembic.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import fakeredis
import pytest
import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pumpwatch.cache.redis_client import PRICE_UPDATED_CHANNEL, cache_key_for
from pumpwatch.config import get_settings
from pumpwatch.db.enums import Priority, SubscriptionStatus
from pumpwatch.db.models import DlqEntry, PriceSnapshot, Subscription, Token, User
from pumpwatch.scheduler import tasks as scheduler_tasks
from pumpwatch.sources.base import TokenSnapshot
from pumpwatch.sources.fake import FakePriceDataSource
from tests.celery_helpers import eager_celery  # noqa: F401  (fixture import)

pytestmark = pytest.mark.usefixtures("eager_celery")


async def _run_batch() -> dict[str, int]:
    return await asyncio.to_thread(lambda: scheduler_tasks.fetch_batch.delay().get())


async def _run_fetch_token(address: str) -> dict[str, Any]:
    return await asyncio.to_thread(lambda: scheduler_tasks.fetch_token.delay(address).get())


async def _seed_one_active_sub(
    sm: async_sessionmaker[AsyncSession],
    *,
    address: str = "tokABC",
    priority: Priority = Priority.HIGH,
) -> int:
    """Create one user + token + active subscription. Returns the sub id."""
    async with sm() as session, session.begin():
        user = User(telegram_id=42, chat_id=42, telegram_username="t")
        session.add(user)
        await session.flush()
        session.add(Token(address=address, symbol="X", name="X"))
        await session.flush()
        sub = Subscription(
            user_id=user.id,
            token_address=address,
            growth_threshold_pct=Decimal("20"),
            stoploss_threshold_pct=Decimal("15"),
            priority=priority,
        )
        session.add(sub)
        await session.flush()
        return sub.id


def _fake_snapshot(address: str) -> TokenSnapshot:
    return TokenSnapshot(
        address=address,
        symbol="X",
        name="X",
        market_cap_usd=Decimal("1000"),
        price_usd=None,
        volume_5m_usd=Decimal("100"),
        liquidity_usd=None,
        holder_count=None,
        source="fake",
        fetched_at=datetime(2026, 4, 24, 12, 0, tzinfo=UTC),
    )


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> aioredis.Redis:
    """Patch the worker-side Redis factory to return an in-memory fake.

    Each test gets a fresh ``FakeAsyncRedis``; the factory returns the
    same instance on every call within the test so assertions about
    cache state can inspect it directly.
    """
    client = cast(aioredis.Redis, fakeredis.FakeAsyncRedis())
    monkeypatch.setattr(scheduler_tasks, "_build_worker_redis", lambda: client)
    return client


async def test_fetch_batch_dispatches_one_task_per_unique_token(
    scheduler_sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sub_id = await _seed_one_active_sub(scheduler_sessionmaker, address="tokABC")
    monkeypatch.setattr(scheduler_tasks, "get_sessionmaker", lambda: scheduler_sessionmaker)

    dispatched: list[tuple[Any, ...]] = []

    def _record(*args: Any, **kwargs: Any) -> None:
        dispatched.append((args, kwargs))

    monkeypatch.setattr(scheduler_tasks.fetch_token, "apply_async", _record)

    result = await _run_batch()

    assert result == {"tokens": 1, "high": 0, "medium": 0, "low": 1}
    assert len(dispatched) == 1
    _args, kwargs = dispatched[0]
    assert kwargs["args"] == ["tokABC"]
    assert kwargs["queue"] == "low"

    # Sub priority got persisted (even with no snapshots, the LOW assignment
    # is still written).
    async with scheduler_sessionmaker() as session:
        sub = (
            await session.execute(select(Subscription).where(Subscription.id == sub_id))
        ).scalar_one()
        # The column is a plain ``String(16)`` with a CHECK constraint; SA
        # returns a str here. ``StrEnum`` instances compare equal to their
        # string value.
        assert sub.priority == Priority.LOW


async def test_fetch_batch_dedups_two_subs_same_token(
    scheduler_sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two users on the same token → still one fetch_token dispatch."""
    async with scheduler_sessionmaker() as session, session.begin():
        u1 = User(telegram_id=1, chat_id=1, telegram_username="a")
        u2 = User(telegram_id=2, chat_id=2, telegram_username="b")
        session.add_all([u1, u2])
        await session.flush()
        session.add(Token(address="tokSHARED"))
        await session.flush()
        session.add_all(
            [
                Subscription(
                    user_id=u1.id,
                    token_address="tokSHARED",
                    growth_threshold_pct=Decimal("10"),
                    stoploss_threshold_pct=Decimal("10"),
                ),
                Subscription(
                    user_id=u2.id,
                    token_address="tokSHARED",
                    growth_threshold_pct=Decimal("10"),
                    stoploss_threshold_pct=Decimal("10"),
                ),
            ]
        )

    monkeypatch.setattr(scheduler_tasks, "get_sessionmaker", lambda: scheduler_sessionmaker)
    dispatched: list[Any] = []
    monkeypatch.setattr(
        scheduler_tasks.fetch_token,
        "apply_async",
        lambda *a, **kw: dispatched.append(kw),
    )

    result = await _run_batch()
    assert result["tokens"] == 1
    assert len(dispatched) == 1


async def test_fetch_batch_skips_stopped_subs(
    scheduler_sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with scheduler_sessionmaker() as session, session.begin():
        user = User(telegram_id=99, chat_id=99, telegram_username="z")
        session.add(user)
        await session.flush()
        session.add(Token(address="tokSTOP"))
        await session.flush()
        session.add(
            Subscription(
                user_id=user.id,
                token_address="tokSTOP",
                growth_threshold_pct=Decimal("20"),
                stoploss_threshold_pct=Decimal("15"),
                status=SubscriptionStatus.STOPPED,
            )
        )

    monkeypatch.setattr(scheduler_tasks, "get_sessionmaker", lambda: scheduler_sessionmaker)
    dispatched: list[Any] = []
    monkeypatch.setattr(
        scheduler_tasks.fetch_token,
        "apply_async",
        lambda *a, **kw: dispatched.append(kw),
    )

    result = await _run_batch()
    assert result == {"tokens": 0, "high": 0, "medium": 0, "low": 0}
    assert dispatched == []


async def test_fetch_token_persists_snapshot_cache_and_publish(
    scheduler_sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: aioredis.Redis,
) -> None:
    """Happy path: snapshot row is written, cache populated, event published."""
    await _seed_one_active_sub(scheduler_sessionmaker, address="tokHOT", priority=Priority.HIGH)
    snap = _fake_snapshot("tokHOT")
    fake = FakePriceDataSource({"tokHOT": [snap]})
    monkeypatch.setattr(scheduler_tasks, "_build_source", lambda _sm: fake)
    monkeypatch.setattr(scheduler_tasks, "get_sessionmaker", lambda: scheduler_sessionmaker)

    # Subscribe before we publish — Redis pub-sub is fire-and-forget.
    pubsub = fake_redis.pubsub()
    await pubsub.subscribe(PRICE_UPDATED_CHANNEL)
    for _ in range(5):
        confirm = await pubsub.get_message(ignore_subscribe_messages=False, timeout=0.05)
        if confirm and confirm.get("type") == "subscribe":
            break

    result = await _run_fetch_token("tokHOT")
    assert result == {"address": "tokHOT", "fetched": True, "tier": "high"}

    async with scheduler_sessionmaker() as session:
        rows = (
            (
                await session.execute(
                    select(PriceSnapshot).where(PriceSnapshot.token_address == "tokHOT")
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].market_cap_usd == Decimal("1000")
        assert rows[0].source == "fake"

    raw = await fake_redis.get(cache_key_for("tokHOT"))
    assert raw is not None
    cached = json.loads(raw)
    assert cached["address"] == "tokHOT"
    assert cached["tier"] == "high"
    assert cached["market_cap_usd"] == "1000"

    ttl = await fake_redis.ttl(cache_key_for("tokHOT"))
    assert 0 < ttl <= 60  # HIGH TTL

    # Drain up to 20 messages waiting for our publish.
    published: dict[str, Any] | None = None
    for _ in range(20):
        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
        if msg is not None:
            published = json.loads(msg["data"])
            break
        await asyncio.sleep(0.01)
    assert published is not None, "expected a pw:price.updated publish"
    assert published["address"] == "tokHOT"
    assert published["tier"] == "high"
    assert published["cache_key"] == cache_key_for("tokHOT")
    await pubsub.aclose()  # type: ignore[no-untyped-call]


async def test_fetch_token_returns_not_found_when_source_has_nothing(
    scheduler_sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: aioredis.Redis,  # noqa: ARG001 — prevents real Redis dial
) -> None:
    fake = FakePriceDataSource({})
    monkeypatch.setattr(scheduler_tasks, "_build_source", lambda _sm: fake)
    monkeypatch.setattr(scheduler_tasks, "get_sessionmaker", lambda: scheduler_sessionmaker)

    result = await _run_fetch_token("missing")
    assert result == {"address": "missing", "fetched": False, "reason": "not_found"}


async def test_fetch_token_unavailable_lands_in_dlq_after_retry(
    scheduler_sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: aioredis.Redis,
) -> None:
    """SourceUnavailableError exhausts the retry budget, lands in dlq_entries.

    The silent-skip return shape is preserved so the scheduler's
    re-dispatch logic stays unchanged. No PriceSnapshot or Redis cache.
    Eager mode does not re-run the task body on ``self.retry``, so we
    pin ``WORKER_FETCH_MAX_CELERY_RETRIES=0`` to drive the exhausted-path
    directly. The retry path is exercised in production via Celery's
    real broker, not eager mode.
    """
    monkeypatch.setattr(get_settings(), "WORKER_FETCH_MAX_CELERY_RETRIES", 0)
    await _seed_one_active_sub(scheduler_sessionmaker, address="tokDOWN")
    fake = FakePriceDataSource({}, fail_addresses={"tokDOWN"})
    monkeypatch.setattr(scheduler_tasks, "_build_source", lambda _sm: fake)
    monkeypatch.setattr(scheduler_tasks, "get_sessionmaker", lambda: scheduler_sessionmaker)

    result = await _run_fetch_token("tokDOWN")
    assert result == {"address": "tokDOWN", "fetched": False, "error": "unavailable"}

    async with scheduler_sessionmaker() as session:
        rows = (
            (
                await session.execute(
                    select(PriceSnapshot).where(PriceSnapshot.token_address == "tokDOWN")
                )
            )
            .scalars()
            .all()
        )
        assert rows == []

        dlq = (
            (await session.execute(select(DlqEntry).where(DlqEntry.token_address == "tokDOWN")))
            .scalars()
            .all()
        )
        assert len(dlq) == 1
        assert dlq[0].attempts == 1
        assert "fake forced failure" in dlq[0].error

    assert await fake_redis.get(cache_key_for("tokDOWN")) is None


async def test_fetch_token_dlq_upsert_bumps_attempts_on_repeat_failure(
    scheduler_sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: aioredis.Redis,  # noqa: ARG001 — prevents real Redis dial
) -> None:
    """Same address failing twice across two task runs → attempts=2, single row."""
    monkeypatch.setattr(get_settings(), "WORKER_FETCH_MAX_CELERY_RETRIES", 0)
    await _seed_one_active_sub(scheduler_sessionmaker, address="tokFLAP")
    fake = FakePriceDataSource({}, fail_addresses={"tokFLAP"})
    monkeypatch.setattr(scheduler_tasks, "_build_source", lambda _sm: fake)
    monkeypatch.setattr(scheduler_tasks, "get_sessionmaker", lambda: scheduler_sessionmaker)

    await _run_fetch_token("tokFLAP")
    await _run_fetch_token("tokFLAP")

    async with scheduler_sessionmaker() as session:
        dlq = (
            (await session.execute(select(DlqEntry).where(DlqEntry.token_address == "tokFLAP")))
            .scalars()
            .all()
        )
        assert len(dlq) == 1, "UNIQUE(token_address) must absorb the second logical failure"
        assert dlq[0].attempts == 2
        assert dlq[0].first_seen <= dlq[0].last_seen


async def test_fetch_token_cache_failure_does_not_break_snapshot(
    scheduler_sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: aioredis.Redis,  # noqa: ARG001 — still used to avoid real Redis
) -> None:
    """Monkey-patched set_price_cache raises — snapshot must still commit."""
    await _seed_one_active_sub(scheduler_sessionmaker, address="tokC1")
    snap = _fake_snapshot("tokC1")
    fake = FakePriceDataSource({"tokC1": [snap]})
    monkeypatch.setattr(scheduler_tasks, "_build_source", lambda _sm: fake)
    monkeypatch.setattr(scheduler_tasks, "get_sessionmaker", lambda: scheduler_sessionmaker)

    async def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("cache is sulking")

    monkeypatch.setattr(scheduler_tasks, "set_price_cache", _boom)

    result = await _run_fetch_token("tokC1")
    assert result["fetched"] is True

    async with scheduler_sessionmaker() as session:
        rows = (
            (
                await session.execute(
                    select(PriceSnapshot).where(PriceSnapshot.token_address == "tokC1")
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1


async def test_fetch_token_publish_failure_does_not_break_snapshot(
    scheduler_sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: aioredis.Redis,
) -> None:
    """Monkey-patched publish_price_updated raises — snapshot still committed."""
    await _seed_one_active_sub(scheduler_sessionmaker, address="tokC2")
    snap = _fake_snapshot("tokC2")
    fake = FakePriceDataSource({"tokC2": [snap]})
    monkeypatch.setattr(scheduler_tasks, "_build_source", lambda _sm: fake)
    monkeypatch.setattr(scheduler_tasks, "get_sessionmaker", lambda: scheduler_sessionmaker)

    async def _boom(*_args: Any, **_kwargs: Any) -> int:
        raise RuntimeError("publish is sulking")

    monkeypatch.setattr(scheduler_tasks, "publish_price_updated", _boom)

    result = await _run_fetch_token("tokC2")
    assert result["fetched"] is True

    async with scheduler_sessionmaker() as session:
        rows = (
            (
                await session.execute(
                    select(PriceSnapshot).where(PriceSnapshot.token_address == "tokC2")
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1

    # The cache still got written (only publish failed).
    assert await fake_redis.get(cache_key_for("tokC2")) is not None


async def test_fetch_token_tier_derives_from_live_priority(
    scheduler_sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: aioredis.Redis,
) -> None:
    """Sub seeded as MEDIUM → cache TTL medium-range, payload tier='medium'."""
    await _seed_one_active_sub(scheduler_sessionmaker, address="tokMED", priority=Priority.MEDIUM)
    snap = _fake_snapshot("tokMED")
    fake = FakePriceDataSource({"tokMED": [snap]})
    monkeypatch.setattr(scheduler_tasks, "_build_source", lambda _sm: fake)
    monkeypatch.setattr(scheduler_tasks, "get_sessionmaker", lambda: scheduler_sessionmaker)

    result = await _run_fetch_token("tokMED")
    assert result["tier"] == "medium"

    ttl = await fake_redis.ttl(cache_key_for("tokMED"))
    assert 60 < ttl <= 300  # MEDIUM TTL, definitely not HIGH's 60


async def test_fetch_token_tier_falls_back_to_low_without_subs(
    scheduler_sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: aioredis.Redis,
) -> None:
    """Race: user stopped sub between dispatch and fetch → tier=LOW."""
    async with scheduler_sessionmaker() as session, session.begin():
        session.add(Token(address="tokORPH"))
    snap = _fake_snapshot("tokORPH")
    fake = FakePriceDataSource({"tokORPH": [snap]})
    monkeypatch.setattr(scheduler_tasks, "_build_source", lambda _sm: fake)
    monkeypatch.setattr(scheduler_tasks, "get_sessionmaker", lambda: scheduler_sessionmaker)

    result = await _run_fetch_token("tokORPH")
    assert result["tier"] == "low"

    ttl = await fake_redis.ttl(cache_key_for("tokORPH"))
    assert 300 < ttl <= 900  # LOW TTL


async def test_fetch_batch_uses_recent_snapshots_to_drive_priority(
    scheduler_sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sub on a token with snapshots near its growth threshold → HIGH tier."""
    async with scheduler_sessionmaker() as session, session.begin():
        user = User(telegram_id=7, chat_id=7, telegram_username="hi")
        session.add(user)
        await session.flush()
        session.add(Token(address="tokHOT"))
        await session.flush()
        session.add(
            Subscription(
                user_id=user.id,
                token_address="tokHOT",
                growth_threshold_pct=Decimal("10"),  # 10% growth target
                stoploss_threshold_pct=Decimal("100"),
            )
        )
        # Two snapshots showing ~9% growth → distance to growth = ~1pp → HIGH.
        # Set ``ts`` explicitly so the newer / older ordering is deterministic
        # regardless of how fast the sequential INSERTs run.
        now = datetime.now(UTC)
        session.add_all(
            [
                PriceSnapshot(
                    token_address="tokHOT",
                    market_cap_usd=Decimal("1000"),
                    ts=now - timedelta(minutes=5),
                ),
                PriceSnapshot(
                    token_address="tokHOT",
                    market_cap_usd=Decimal("1090"),
                    ts=now,
                ),
            ]
        )

    monkeypatch.setattr(scheduler_tasks, "get_sessionmaker", lambda: scheduler_sessionmaker)
    dispatched: list[Any] = []
    monkeypatch.setattr(
        scheduler_tasks.fetch_token,
        "apply_async",
        lambda *a, **kw: dispatched.append(kw),
    )

    result = await _run_batch()
    assert result["high"] == 1
    assert dispatched[0]["queue"] == "high"
