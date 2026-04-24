"""End-to-end tests for the scheduler Celery tasks (eager mode + test DB).

The tasks themselves wrap their async bodies in ``asyncio.run``, which
cannot be called from inside pytest-asyncio's event loop. We hop each
``.delay()`` call onto a worker thread via ``asyncio.to_thread``, mirroring
the pattern ``tests/conftest.py`` uses for Alembic.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pumpwatch.db.enums import Priority, SubscriptionStatus
from pumpwatch.db.models import PriceSnapshot, Subscription, Token, User
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
        fetched_at=datetime.now(UTC),
    )


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


async def test_fetch_token_calls_source_and_returns_summary(
    scheduler_sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakePriceDataSource({"tokABC": [_fake_snapshot("tokABC")]})
    monkeypatch.setattr(scheduler_tasks, "_build_pumpfun_client", lambda _sm: fake)
    monkeypatch.setattr(scheduler_tasks, "get_sessionmaker", lambda: scheduler_sessionmaker)

    result = await _run_fetch_token("tokABC")
    assert result == {"address": "tokABC", "found": True}


async def test_fetch_token_returns_not_found_when_source_has_nothing(
    scheduler_sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakePriceDataSource({})
    monkeypatch.setattr(scheduler_tasks, "_build_pumpfun_client", lambda _sm: fake)
    monkeypatch.setattr(scheduler_tasks, "get_sessionmaker", lambda: scheduler_sessionmaker)

    result = await _run_fetch_token("missing")
    assert result == {"address": "missing", "found": False}


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
