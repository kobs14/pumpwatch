"""Telegram dispatcher for the alerts service.

Holds one ``telegram.Bot`` (initialised once, reused for every send)
plus two ``aiolimiter.AsyncLimiter`` instances:

* a single global limiter (``TELEGRAM_GLOBAL_MSG_PER_SEC``) — Telegram
  enforces ~30 msg/sec across the whole bot;
* a per-chat limiter (``TELEGRAM_PER_CHAT_MSG_PER_SEC``, default 1) —
  Telegram enforces ~1 msg/sec per chat.

Dispatch sequence: acquire global, acquire per-chat, ``send_message``.
On failure, wait ``ALERT_DISPATCH_RETRY_DELAY_SECONDS`` and try once
more. Second failure raises; the subscriber records the error on the
already-persisted alert row and keeps consuming.

Same token can run alongside the bot service safely: only one process
calls ``getUpdates`` (the bot), so there's no Update-fetch conflict.
Outbound calls are HTTP and do not collide.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from decimal import Decimal

from aiolimiter import AsyncLimiter
from telegram import Bot
from telegram.error import TelegramError

from pumpwatch.alerts.detectors import AlertCandidate
from pumpwatch.config import Settings
from pumpwatch.db.enums import AlertType
from pumpwatch.db.models import Subscription, Token
from pumpwatch.logging import get_logger

_log = get_logger(__name__)


def _truncate_mint(address: str) -> str:
    if len(address) <= 10:
        return address
    return f"{address[:4]}…{address[-4:]}"


def _fmt_decimal(value: str | Decimal | None, places: int = 2) -> str:
    if value is None:
        return "?"
    if isinstance(value, str):
        try:
            decimal_value = Decimal(value)
        except (ArithmeticError, ValueError):
            return value
        return f"{decimal_value:.{places}f}"
    return f"{value:.{places}f}"


def format_alert_text(
    candidate: AlertCandidate,
    subscription: Subscription,
    token: Token | None,
) -> str:
    """Render an alert candidate as a plain-text Telegram message.

    Plain text (not MarkdownV2) by deliberate choice: alert payloads
    contain user-supplied numbers and a token symbol, and the cost of
    one missed escape is a broken send. Plain text always works.
    """
    label = (token.symbol if token and token.symbol else None) or _truncate_mint(
        subscription.token_address
    )
    addr = _truncate_mint(subscription.token_address)
    payload = candidate.payload

    if candidate.alert_type == AlertType.GROWTH_HIT:
        return (
            f"🚀 {label} hit +{_fmt_decimal(payload.get('threshold_pct'))}% growth\n"
            f"   {_fmt_decimal(payload.get('baseline_market_cap'), 0)} → "
            f"{_fmt_decimal(payload.get('current_market_cap'), 0)} "
            f"({_fmt_decimal(payload.get('delta_pct'))}%)\n"
            f"   {addr}"
        )
    if candidate.alert_type == AlertType.GROWTH_WARNING:
        return (
            f"📈 {label} approaching +{_fmt_decimal(payload.get('threshold_pct'))}% growth\n"
            f"   currently {_fmt_decimal(payload.get('delta_pct'))}% above baseline\n"
            f"   {addr}"
        )
    if candidate.alert_type == AlertType.STOPLOSS_HIT:
        return (
            f"🔻 {label} hit -{_fmt_decimal(payload.get('threshold_pct'))}% stoploss\n"
            f"   {_fmt_decimal(payload.get('baseline_market_cap'), 0)} → "
            f"{_fmt_decimal(payload.get('current_market_cap'), 0)} "
            f"(-{_fmt_decimal(payload.get('drop_pct'))}%)\n"
            f"   {addr}"
        )
    if candidate.alert_type == AlertType.STOPLOSS_WARNING:
        return (
            f"⚠️ {label} approaching -{_fmt_decimal(payload.get('threshold_pct'))}% stoploss\n"
            f"   currently -{_fmt_decimal(payload.get('drop_pct'))}% from baseline\n"
            f"   {addr}"
        )
    # VOLUME_SPIKE
    return (
        f"📊 {label} unusual volume spike\n"
        f"   5m volume {_fmt_decimal(payload.get('current_volume_5m_usd'))} "
        f"(median {_fmt_decimal(payload.get('median_volume_5m_usd'))}, "
        f"score {_fmt_decimal(payload.get('score'))})\n"
        f"   {addr}"
    )


class TelegramDispatcher:
    """Outbound Telegram client with per-chat + global rate limiting."""

    def __init__(self, bot: Bot, settings: Settings) -> None:
        self._bot = bot
        self._retry_delay = settings.ALERT_DISPATCH_RETRY_DELAY_SECONDS
        self._global = AsyncLimiter(max(1, settings.TELEGRAM_GLOBAL_MSG_PER_SEC), 1)
        per_chat_rate = max(1, settings.TELEGRAM_PER_CHAT_MSG_PER_SEC)
        self._per_chat: dict[int, AsyncLimiter] = defaultdict(
            lambda: AsyncLimiter(per_chat_rate, 1)
        )

    async def send_alert(self, chat_id: int, text: str) -> None:
        """Send ``text`` to ``chat_id``. One inline retry on failure.

        Raises the second exception so the caller can persist the failure
        on the alert row. Loop is expected to keep consuming.
        """
        async with self._global, self._per_chat[chat_id]:
            try:
                await self._bot.send_message(chat_id=chat_id, text=text)
                return
            except TelegramError as exc:
                _log.warning(
                    "alerts.dispatch.first_attempt_failed",
                    chat_id=chat_id,
                    error=str(exc),
                )

            await asyncio.sleep(self._retry_delay)
            await self._bot.send_message(chat_id=chat_id, text=text)


async def build_dispatcher(token: str, settings: Settings) -> TelegramDispatcher:
    """Construct + initialise a dispatcher.

    Two-layer guard: client construction is wrapped here; per-call RPC
    failures are wrapped in ``send_alert``. Initialisation failure is
    fatal — the alerts service can't run without a working Bot.
    """
    bot = Bot(token=token)
    await bot.initialize()
    return TelegramDispatcher(bot, settings)


async def shutdown_dispatcher(dispatcher: TelegramDispatcher) -> None:
    """Best-effort shutdown of the underlying ``Bot``."""
    try:
        await dispatcher._bot.shutdown()
    except Exception as exc:  # noqa: BLE001 — best-effort shutdown
        _log.warning("alerts.dispatcher.shutdown_failed", error=str(exc))
