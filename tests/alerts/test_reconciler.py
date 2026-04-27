"""Reconciler tests — exercises the end-to-end re-dispatch path.

The Celery task wraps ``_reconcile_async`` in ``asyncio.run``; tests
call the async helper directly to avoid the eager-mode loop conflict.
A separate test confirms the Celery wrapper kicks the helper through.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pumpwatch.alerts import reconciler as reconciler_mod
from pumpwatch.alerts import tasks as alerts_tasks
from pumpwatch.alerts.dispatcher import TelegramDispatcher
from pumpwatch.config import get_settings
from pumpwatch.db.enums import AlertType, Priority, SubscriptionStatus
from pumpwatch.db.models import AlertSent, Subscription, Token, User
from tests.celery_helpers import eager_celery  # noqa: F401  (fixture import)


class _RecordingDispatcher:
    """Stand-in for ``TelegramDispatcher``."""

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
    address: str = "addrR001",
    chat_id: int = 7001,
    telegram_id: int = 7001,
    alerts_muted: bool = False,
) -> tuple[int, int, str]:
    """Seed user + token + active subscription. Returns (user_id, sub_id, address)."""
    async with sm() as s, s.begin():
        u = User(
            telegram_id=telegram_id,
            chat_id=chat_id,
            telegram_username=f"u{telegram_id}",
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
            baseline_market_cap=Decimal("100"),
            priority=Priority.HIGH,
            status=SubscriptionStatus.ACTIVE,
        )
        s.add(sub)
        await s.flush()
        return u.id, sub.id, address


async def _seed_failed_alert(
    sm: async_sessionmaker[AsyncSession],
    *,
    sub_id: int,
    error: str = "boom",
    dispatch_attempts: int = 1,
    age_seconds: int = 60,
    payload: dict[str, Any] | None = None,
    alert_type: AlertType = AlertType.GROWTH_HIT,
) -> int:
    """Insert a failed alert row and return its id."""
    if payload is None:
        payload = {
            "threshold_pct": "10.00",
            "baseline_market_cap": "100",
            "current_market_cap": "115",
            "delta_pct": "15.00",
        }
    async with sm() as s, s.begin():
        alert = AlertSent(
            subscription_id=sub_id,
            alert_type=alert_type.value,
            triggered_at_market_cap=Decimal("115"),
            payload_json=payload,
            delivered=False,
            delivery_error=error,
            dispatch_attempts=dispatch_attempts,
            created_at=datetime.now(UTC) - timedelta(seconds=age_seconds),
        )
        s.add(alert)
        await s.flush()
        return alert.id


@pytest.fixture
def patched_dispatcher(monkeypatch: pytest.MonkeyPatch) -> _RecordingDispatcher:
    """Patch ``build_dispatcher`` to return a recording stand-in."""
    rec = _RecordingDispatcher()

    async def _build(_token: str, _settings: Any) -> _RecordingDispatcher:
        return rec

    async def _shutdown(_dispatcher: TelegramDispatcher) -> None:
        return None

    monkeypatch.setattr(reconciler_mod, "build_dispatcher", _build)
    monkeypatch.setattr(reconciler_mod, "shutdown_dispatcher", _shutdown)
    return rec


async def test_reconciler_redelivers_failed_alert(
    alerts_sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    patched_dispatcher: _RecordingDispatcher,
) -> None:
    _, sub_id, _ = await _seed(alerts_sessionmaker, telegram_id=1, chat_id=1001)
    alert_id = await _seed_failed_alert(alerts_sessionmaker, sub_id=sub_id)
    monkeypatch.setattr(reconciler_mod, "get_sessionmaker", lambda: alerts_sessionmaker)

    counts = await reconciler_mod._reconcile_async()

    assert counts == {
        "candidates": 1,
        "redelivered": 1,
        "failed_again": 0,
        "suppressed_now": 0,
    }
    assert len(patched_dispatcher.calls) == 1
    chat_id, text = patched_dispatcher.calls[0]
    assert chat_id == 1001
    assert "10.00" in text  # threshold_pct in formatted output

    async with alerts_sessionmaker() as s:
        row = (await s.execute(select(AlertSent).where(AlertSent.id == alert_id))).scalar_one()
    assert row.delivered is True
    assert row.delivery_error is None
    assert row.dispatch_attempts == 2


async def test_reconciler_skips_suppressed_rows(
    alerts_sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    patched_dispatcher: _RecordingDispatcher,
) -> None:
    """ADR #17: rows with delivery_error LIKE 'suppressed:%' are never re-sent."""
    _, sub_id, _ = await _seed(alerts_sessionmaker, telegram_id=2, chat_id=1002)
    alert_id = await _seed_failed_alert(
        alerts_sessionmaker,
        sub_id=sub_id,
        error="suppressed: muted",
    )
    monkeypatch.setattr(reconciler_mod, "get_sessionmaker", lambda: alerts_sessionmaker)

    counts = await reconciler_mod._reconcile_async()

    assert counts["candidates"] == 0  # SQL filter excludes it entirely
    assert patched_dispatcher.calls == []

    async with alerts_sessionmaker() as s:
        row = (await s.execute(select(AlertSent).where(AlertSent.id == alert_id))).scalar_one()
    assert row.delivered is False
    assert row.delivery_error == "suppressed: muted"
    assert row.dispatch_attempts == 1  # untouched


async def test_reconciler_skips_rows_outside_window(
    alerts_sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    patched_dispatcher: _RecordingDispatcher,
) -> None:
    _, sub_id, _ = await _seed(alerts_sessionmaker, telegram_id=3, chat_id=1003)
    settings = get_settings()
    too_old = settings.ALERT_RECONCILE_WINDOW_SECONDS + 60
    await _seed_failed_alert(alerts_sessionmaker, sub_id=sub_id, age_seconds=too_old)
    monkeypatch.setattr(reconciler_mod, "get_sessionmaker", lambda: alerts_sessionmaker)

    counts = await reconciler_mod._reconcile_async()
    assert counts["candidates"] == 0
    assert patched_dispatcher.calls == []


async def test_reconciler_skips_rows_at_max_attempts(
    alerts_sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    patched_dispatcher: _RecordingDispatcher,
) -> None:
    """A row already touched once by the reconciler is left alone the next sweep."""
    _, sub_id, _ = await _seed(alerts_sessionmaker, telegram_id=4, chat_id=1004)
    settings = get_settings()
    # Default ALERT_RECONCILE_MAX_ATTEMPTS = 1; a row at dispatch_attempts=2
    # has already been re-tried once and should not be picked up again.
    await _seed_failed_alert(
        alerts_sessionmaker,
        sub_id=sub_id,
        dispatch_attempts=settings.ALERT_RECONCILE_MAX_ATTEMPTS + 1,
    )
    monkeypatch.setattr(reconciler_mod, "get_sessionmaker", lambda: alerts_sessionmaker)

    counts = await reconciler_mod._reconcile_async()
    assert counts["candidates"] == 0
    assert patched_dispatcher.calls == []


async def test_reconciler_marks_failed_again_on_dispatcher_error(
    alerts_sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    patched_dispatcher: _RecordingDispatcher,
) -> None:
    _, sub_id, _ = await _seed(alerts_sessionmaker, telegram_id=5, chat_id=1005)
    alert_id = await _seed_failed_alert(alerts_sessionmaker, sub_id=sub_id)
    patched_dispatcher.raise_with = RuntimeError("telegram still down")
    monkeypatch.setattr(reconciler_mod, "get_sessionmaker", lambda: alerts_sessionmaker)

    counts = await reconciler_mod._reconcile_async()

    assert counts == {
        "candidates": 1,
        "redelivered": 0,
        "failed_again": 1,
        "suppressed_now": 0,
    }

    async with alerts_sessionmaker() as s:
        row = (await s.execute(select(AlertSent).where(AlertSent.id == alert_id))).scalar_one()
    assert row.delivered is False
    assert row.delivery_error == "telegram still down"
    assert row.dispatch_attempts == 2


async def test_reconciler_marks_newly_suppressed_user(
    alerts_sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    patched_dispatcher: _RecordingDispatcher,
) -> None:
    """User muted between original failure and reconciler run → mark suppressed (not delivered)."""
    _, sub_id, _ = await _seed(alerts_sessionmaker, telegram_id=6, chat_id=1006, alerts_muted=True)
    alert_id = await _seed_failed_alert(alerts_sessionmaker, sub_id=sub_id)
    monkeypatch.setattr(reconciler_mod, "get_sessionmaker", lambda: alerts_sessionmaker)

    counts = await reconciler_mod._reconcile_async()

    assert counts["suppressed_now"] == 1
    assert counts["redelivered"] == 0
    assert patched_dispatcher.calls == []

    async with alerts_sessionmaker() as s:
        row = (await s.execute(select(AlertSent).where(AlertSent.id == alert_id))).scalar_one()
    assert row.delivered is False
    assert row.delivery_error is not None
    assert row.delivery_error.startswith("suppressed:")
    assert row.dispatch_attempts == 2


@pytest.mark.usefixtures("eager_celery")
async def test_celery_wrapper_delegates_to_async_helper(
    alerts_sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    patched_dispatcher: _RecordingDispatcher,  # noqa: ARG001 — fixture wires dispatcher
) -> None:
    """The @celery.task wrapper must invoke the async reconciler under asyncio.run."""
    _, sub_id, _ = await _seed(alerts_sessionmaker, telegram_id=8, chat_id=1008)
    await _seed_failed_alert(alerts_sessionmaker, sub_id=sub_id)
    monkeypatch.setattr(reconciler_mod, "get_sessionmaker", lambda: alerts_sessionmaker)

    counts = await asyncio.to_thread(lambda: alerts_tasks.reconcile_failed_alerts.delay().get())
    assert counts["redelivered"] == 1
