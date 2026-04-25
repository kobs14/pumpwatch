"""Subscriber-loop logic tested against the real test DB + fakeredis.

Drives ``_process_event`` directly so we don't depend on fakeredis's
pub-sub timing. The integration test in ``tests/integration/`` exercises
the full SUBSCRIBE/PUBLISH path against a real Redis.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import fakeredis.aioredis
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pumpwatch.alerts import subscriber
from pumpwatch.cache.redis_client import alert_dedup_key
from pumpwatch.config import get_settings
from pumpwatch.db.enums import AlertType, Priority
from pumpwatch.db.models import AlertSent, Subscription, Token, User


class _RecordingDispatcher:
    """Stand-in for ``TelegramDispatcher``; captures calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []
        self.raise_with: Exception | None = None

    async def send_alert(self, chat_id: int, text: str) -> None:
        if self.raise_with is not None:
            raise self.raise_with
        self.calls.append((chat_id, text))


async def _seed(
    sm: async_sessionmaker[AsyncSession],
    *,
    baseline: Decimal | None = Decimal("100"),
    alerts_muted: bool = False,
    priority: Priority = Priority.HIGH,
) -> tuple[int, int, str]:
    """Seed user + token + subscription. Returns (user_id, sub_id, address)."""
    address = "addrUNIT001"
    async with sm() as s, s.begin():
        u = User(
            telegram_id=10,
            chat_id=10,
            telegram_username="u",
            alerts_muted=alerts_muted,
        )
        s.add(u)
        await s.flush()
        s.add(Token(address=address, symbol="UNIT", name="Unit"))
        await s.flush()
        sub = Subscription(
            user_id=u.id,
            token_address=address,
            growth_threshold_pct=Decimal("10"),
            stoploss_threshold_pct=Decimal("10"),
            warning_buffer_pct=Decimal("2"),
            volume_spike_k=Decimal("3"),
            baseline_market_cap=baseline,
            priority=priority,
        )
        s.add(sub)
        await s.flush()
        return u.id, sub.id, address


def _payload(address: str, *, market_cap: str = "115", volume: str = "100") -> dict[str, Any]:
    return {
        "address": address,
        "ts": datetime(2026, 4, 24, 12, 0, tzinfo=UTC).isoformat(),
        "source": "fake",
        "tier": Priority.HIGH.value,
        "market_cap_usd": market_cap,
        "price_usd": "1.0",
        "volume_5m_usd": volume,
        "liquidity_usd": "0",
        "holder_count": 1,
        "cache_key": f"pw:price:{address}",
    }


async def _alerts_for(sm: async_sessionmaker[AsyncSession], sub_id: int) -> list[AlertSent]:
    async with sm() as s:
        rows = (
            (await s.execute(select(AlertSent).where(AlertSent.subscription_id == sub_id)))
            .scalars()
            .all()
        )
        return list(rows)


async def test_growth_hit_persists_and_dispatches(
    alerts_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    user_id, sub_id, address = await _seed(alerts_sessionmaker)
    redis_client = fakeredis.aioredis.FakeRedis()
    dispatcher = _RecordingDispatcher()

    await subscriber._process_event(
        sessionmaker=alerts_sessionmaker,
        redis_client=redis_client,
        dispatcher=dispatcher,  # type: ignore[arg-type]
        settings=get_settings(),
        payload=_payload(address, market_cap="115"),
    )

    rows = await _alerts_for(alerts_sessionmaker, sub_id)
    assert len(rows) == 1
    assert rows[0].alert_type == AlertType.GROWTH_HIT.value
    assert rows[0].delivered is True
    assert rows[0].delivery_error is None
    assert dispatcher.calls and dispatcher.calls[0][0] == 10  # chat_id

    # Dedup key should be set.
    assert (
        await redis_client.get(alert_dedup_key(user_id, address, AlertType.GROWTH_HIT)) is not None
    )


async def test_no_alert_when_below_warning_band(
    alerts_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    _, sub_id, address = await _seed(alerts_sessionmaker)
    redis_client = fakeredis.aioredis.FakeRedis()
    dispatcher = _RecordingDispatcher()

    await subscriber._process_event(
        sessionmaker=alerts_sessionmaker,
        redis_client=redis_client,
        dispatcher=dispatcher,  # type: ignore[arg-type]
        settings=get_settings(),
        payload=_payload(address, market_cap="105"),  # +5%, below 8% warning band
    )

    assert await _alerts_for(alerts_sessionmaker, sub_id) == []
    assert dispatcher.calls == []


async def test_dedup_suppresses_second_fire(
    alerts_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    _, sub_id, address = await _seed(alerts_sessionmaker)
    redis_client = fakeredis.aioredis.FakeRedis()
    dispatcher = _RecordingDispatcher()
    settings = get_settings()

    payload = _payload(address, market_cap="115")
    await subscriber._process_event(
        sessionmaker=alerts_sessionmaker,
        redis_client=redis_client,
        dispatcher=dispatcher,  # type: ignore[arg-type]
        settings=settings,
        payload=payload,
    )
    await subscriber._process_event(
        sessionmaker=alerts_sessionmaker,
        redis_client=redis_client,
        dispatcher=dispatcher,  # type: ignore[arg-type]
        settings=settings,
        payload=payload,
    )

    rows = await _alerts_for(alerts_sessionmaker, sub_id)
    assert len(rows) == 1  # Second fire deduped.
    assert len(dispatcher.calls) == 1


async def test_muted_user_persists_but_does_not_dispatch(
    alerts_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    _, sub_id, address = await _seed(alerts_sessionmaker, alerts_muted=True)
    redis_client = fakeredis.aioredis.FakeRedis()
    dispatcher = _RecordingDispatcher()

    await subscriber._process_event(
        sessionmaker=alerts_sessionmaker,
        redis_client=redis_client,
        dispatcher=dispatcher,  # type: ignore[arg-type]
        settings=get_settings(),
        payload=_payload(address, market_cap="115"),
    )

    rows = await _alerts_for(alerts_sessionmaker, sub_id)
    assert len(rows) == 1
    assert rows[0].delivered is False
    assert rows[0].delivery_error == "suppressed: muted"
    assert dispatcher.calls == []


async def test_paused_subscription_persists_but_does_not_dispatch(
    alerts_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    _, sub_id, address = await _seed(alerts_sessionmaker, priority=Priority.PAUSED)
    redis_client = fakeredis.aioredis.FakeRedis()
    dispatcher = _RecordingDispatcher()

    await subscriber._process_event(
        sessionmaker=alerts_sessionmaker,
        redis_client=redis_client,
        dispatcher=dispatcher,  # type: ignore[arg-type]
        settings=get_settings(),
        payload=_payload(address, market_cap="115"),
    )

    rows = await _alerts_for(alerts_sessionmaker, sub_id)
    assert len(rows) == 1
    assert rows[0].delivered is False
    assert rows[0].delivery_error == "suppressed: paused"
    assert dispatcher.calls == []


async def test_dispatch_failure_marks_failed_but_keeps_consuming(
    alerts_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    _, sub_id, address = await _seed(alerts_sessionmaker)
    redis_client = fakeredis.aioredis.FakeRedis()
    dispatcher = _RecordingDispatcher()
    dispatcher.raise_with = RuntimeError("send went boom")

    await subscriber._process_event(
        sessionmaker=alerts_sessionmaker,
        redis_client=redis_client,
        dispatcher=dispatcher,  # type: ignore[arg-type]
        settings=get_settings(),
        payload=_payload(address, market_cap="115"),
    )

    rows = await _alerts_for(alerts_sessionmaker, sub_id)
    assert len(rows) == 1
    assert rows[0].delivered is False
    assert rows[0].delivery_error == "send went boom"


async def test_no_subs_for_token_is_a_noop(
    alerts_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    redis_client = fakeredis.aioredis.FakeRedis()
    dispatcher = _RecordingDispatcher()

    await subscriber._process_event(
        sessionmaker=alerts_sessionmaker,
        redis_client=redis_client,
        dispatcher=dispatcher,  # type: ignore[arg-type]
        settings=get_settings(),
        payload=_payload("addrNONE"),
    )

    assert dispatcher.calls == []


async def test_dedup_redis_failure_falls_back_to_db_backstop(
    alerts_sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, sub_id, address = await _seed(alerts_sessionmaker)
    real_redis = fakeredis.aioredis.FakeRedis()
    dispatcher = _RecordingDispatcher()

    payload = _payload(address, market_cap="115")

    # First run: normal path persists the alert in DB.
    await subscriber._process_event(
        sessionmaker=alerts_sessionmaker,
        redis_client=real_redis,
        dispatcher=dispatcher,  # type: ignore[arg-type]
        settings=get_settings(),
        payload=payload,
    )
    assert len(await _alerts_for(alerts_sessionmaker, sub_id)) == 1

    # Second run: monkey-patch dedup.should_skip to raise so we exercise the
    # DB-backstop branch. The DB row from the first run within the cooldown
    # is what should suppress the second fire.
    async def _boom(*_args: Any, **_kwargs: Any) -> bool:
        raise RuntimeError("redis flake")

    monkeypatch.setattr("pumpwatch.alerts.subscriber.dedup_mod.should_skip", _boom)

    await subscriber._process_event(
        sessionmaker=alerts_sessionmaker,
        redis_client=real_redis,
        dispatcher=dispatcher,  # type: ignore[arg-type]
        settings=get_settings(),
        payload=payload,
    )

    # Still one row — DB backstop saw the recent alert and skipped.
    assert len(await _alerts_for(alerts_sessionmaker, sub_id)) == 1
