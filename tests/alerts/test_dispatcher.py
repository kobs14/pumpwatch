"""TelegramDispatcher tests — formatting and rate-limited send + retry."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram.error import NetworkError

from pumpwatch.alerts.detectors import AlertCandidate
from pumpwatch.alerts.dispatcher import TelegramDispatcher, format_alert_text
from pumpwatch.config import get_settings
from pumpwatch.db.enums import AlertType, Priority, SubscriptionStatus
from pumpwatch.db.models import Subscription, Token


def _sub() -> Subscription:
    return Subscription(
        user_id=1,
        token_address="abcdefghijklmnop",
        growth_threshold_pct=Decimal("10"),
        stoploss_threshold_pct=Decimal("10"),
        priority=Priority.HIGH,
        status=SubscriptionStatus.ACTIVE,
    )


def _token(symbol: str | None = "FOO") -> Token:
    return Token(address="abcdefghijklmnop", symbol=symbol, name="FooBar")


def _candidate_growth_hit() -> AlertCandidate:
    return AlertCandidate(
        alert_type=AlertType.GROWTH_HIT,
        market_cap=Decimal("110"),
        payload={
            "baseline_market_cap": "100",
            "current_market_cap": "110",
            "delta_pct": "10.00",
            "threshold_pct": "10",
        },
    )


def test_format_alert_uses_token_symbol_when_present() -> None:
    text = format_alert_text(_candidate_growth_hit(), _sub(), _token())
    assert "FOO" in text
    assert "🚀" in text


def test_format_alert_falls_back_to_truncated_mint_when_no_symbol() -> None:
    text = format_alert_text(_candidate_growth_hit(), _sub(), _token(symbol=None))
    assert "abcd…mnop" in text


def test_format_alert_handles_each_alert_type() -> None:
    sub = _sub()
    token = _token()
    cases: list[tuple[AlertType, dict[str, Any]]] = [
        (
            AlertType.GROWTH_HIT,
            {
                "baseline_market_cap": "100",
                "current_market_cap": "110",
                "delta_pct": "10",
                "threshold_pct": "10",
            },
        ),
        (AlertType.GROWTH_WARNING, {"delta_pct": "8", "threshold_pct": "10"}),
        (
            AlertType.STOPLOSS_HIT,
            {
                "baseline_market_cap": "100",
                "current_market_cap": "90",
                "drop_pct": "10",
                "threshold_pct": "10",
            },
        ),
        (AlertType.STOPLOSS_WARNING, {"drop_pct": "8", "threshold_pct": "10"}),
        (
            AlertType.VOLUME_SPIKE,
            {
                "current_volume_5m_usd": "100",
                "median_volume_5m_usd": "10",
                "score": "5",
                "k": "3",
                "samples": 12,
            },
        ),
    ]
    for atype, payload in cases:
        cand = AlertCandidate(alert_type=atype, market_cap=None, payload=payload)
        text = format_alert_text(cand, sub, token)
        assert "FOO" in text
        assert "abcd…mnop" in text


def _fake_bot(*, raises: list[Any] | None = None) -> Any:
    bot = MagicMock()
    if raises:
        bot.send_message = AsyncMock(side_effect=raises)
    else:
        bot.send_message = AsyncMock(return_value=None)
    return bot


async def test_dispatcher_send_alert_calls_bot(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = _fake_bot()
    dispatcher = TelegramDispatcher(bot, get_settings())
    await dispatcher.send_alert(99, "hello")
    bot.send_message.assert_awaited_once_with(chat_id=99, text="hello")


async def test_dispatcher_retries_once_on_telegram_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("pumpwatch.alerts.dispatcher.asyncio.sleep", _fake_sleep)

    # First call raises, second succeeds.
    bot = _fake_bot(raises=[NetworkError("boom"), None])
    dispatcher = TelegramDispatcher(bot, get_settings())

    await dispatcher.send_alert(99, "hello")

    assert bot.send_message.await_count == 2
    assert sleeps and sleeps[0] == get_settings().ALERT_DISPATCH_RETRY_DELAY_SECONDS


async def test_dispatcher_raises_after_second_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("pumpwatch.alerts.dispatcher.asyncio.sleep", _no_sleep)

    bot = _fake_bot(raises=[NetworkError("first"), NetworkError("second")])
    dispatcher = TelegramDispatcher(bot, get_settings())

    with pytest.raises(NetworkError, match="second"):
        await dispatcher.send_alert(99, "hello")
    assert bot.send_message.await_count == 2
