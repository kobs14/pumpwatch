"""Pub-sub subscriber loop for the alert engine.

Subscribes to ``pw:price.updated`` once at startup, then drains messages
forever. For each event it loads the active subs, evaluates threshold +
volume-spike detectors, dedupes via Redis (with DB-side backstop),
checks suppression (mute / paused / quiet hours), persists every fired
alert, then dispatches via the Telegram dispatcher.

CLAUDE.md invariants enforced here:

* **Persist before dispatch** — ``AlertRepository.record(...)`` runs
  inside its own transaction; the Telegram call only happens after the
  row is committed. Dispatch failure flips ``delivered_error`` on the
  already-persisted row.
* **Suppress but persist** — muted / quiet-hours / PAUSED alerts still
  hit ``alerts_sent`` (with ``delivered=False``, ``delivery_error="suppressed: ..."``)
  *and* the dedup TTL key still gets set. Unmute does not replay a
  thundering herd of stale warnings.
* **Per-sub failure does not abort the loop** — every per-sub error is
  caught + logged, and the loop keeps consuming.

Pub-sub has no replay; the alerts service must be running before Beat
fires its first ``fetch_batch`` or events between startups are lost
(Postgres snapshot rows remain the source of truth for any backfill).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pumpwatch.alerts import dedup as dedup_mod
from pumpwatch.alerts.detectors import (
    AlertCandidate,
    evaluate_thresholds,
    evaluate_volume_spike,
)
from pumpwatch.alerts.dispatcher import TelegramDispatcher, format_alert_text
from pumpwatch.alerts.suppression import is_suppressed
from pumpwatch.cache.redis_client import PRICE_UPDATED_CHANNEL
from pumpwatch.config import Settings, get_settings
from pumpwatch.db.models import Subscription, Token, User
from pumpwatch.db.repos.alert import AlertRepository
from pumpwatch.db.repos.price_snapshot import PriceSnapshotRepository
from pumpwatch.db.repos.subscription import SubscriptionRepository
from pumpwatch.logging import get_logger

_log = get_logger(__name__)


def _redact(address: str) -> str:
    return f"{address[:4]}...{address[-4:]}" if len(address) > 8 else address


def _decimal_or_none(raw: Any) -> Decimal | None:
    if raw is None:
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None


async def _load_token(session: AsyncSession, address: str) -> Token | None:
    return (
        await session.execute(select(Token).where(Token.address == address))
    ).scalar_one_or_none()


async def _load_users(session: AsyncSession, user_ids: set[int]) -> dict[int, User]:
    if not user_ids:
        return {}
    stmt = select(User).where(User.id.in_(user_ids))
    rows = (await session.execute(stmt)).scalars().all()
    return {u.id: u for u in rows}


async def _load_volume_history(
    session: AsyncSession,
    address: str,
    settings: Settings,
    event_ts: datetime,
) -> list[Decimal | None]:
    """Pull the rolling ``volume_5m_usd`` history, excluding the current bar.

    The current snapshot is already persisted by the time we receive the
    pub-sub event (worker commits before publishing), so it'd otherwise
    bias the median toward itself.
    """
    since = event_ts - timedelta(seconds=settings.VOLUME_SPIKE_WINDOW_SECONDS)
    rows = await PriceSnapshotRepository(session).history_for_token(address, since=since)
    return [r.volume_5m_usd for r in rows if r.ts < event_ts]


async def _persist_alert(
    sessionmaker: async_sessionmaker[AsyncSession],
    subscription_id: int,
    candidate: AlertCandidate,
) -> int:
    """Open a short transaction, write the alert row, return its id."""
    async with sessionmaker() as session, session.begin():
        alert = await AlertRepository(session).record(
            subscription_id=subscription_id,
            alert_type=candidate.alert_type,
            market_cap=candidate.market_cap,
            payload=candidate.payload,
        )
        return alert.id


async def _mark_delivered(
    sessionmaker: async_sessionmaker[AsyncSession],
    alert_id: int,
) -> None:
    async with sessionmaker() as session, session.begin():
        await AlertRepository(session).mark_delivered(alert_id)


async def _mark_failed(
    sessionmaker: async_sessionmaker[AsyncSession],
    alert_id: int,
    error: str,
) -> None:
    async with sessionmaker() as session, session.begin():
        await AlertRepository(session).mark_delivery_failed(alert_id, error)


async def _dedup_skip_with_fallback(
    redis_client: aioredis.Redis,
    sessionmaker: async_sessionmaker[AsyncSession],
    subscription_id: int,
    user_id: int,
    address: str,
    candidate: AlertCandidate,
    ttl_seconds: int,
) -> bool:
    """Return True if we should skip due to dedup.

    Checks Redis first (fast); on Redis failure falls back to the
    DB-side backstop (``recent_for_subscription``). This is the
    Session 5 two-layer defensive shape: Redis flake never blocks
    dispatch, but a hot redis hit also doesn't pay for a DB read.
    """
    try:
        if await dedup_mod.should_skip(redis_client, user_id, address, candidate.alert_type):
            return True
    except Exception as exc:  # noqa: BLE001 — best-effort, fall back to DB
        _log.warning(
            "alerts.dedup.redis_failed",
            address=_redact(address),
            user_id=user_id,
            alert_type=candidate.alert_type.value,
            error=str(exc),
        )

    async with sessionmaker() as session:
        recent = await AlertRepository(session).recent_for_subscription(
            subscription_id=subscription_id,
            alert_type=candidate.alert_type,
            within_seconds=ttl_seconds,
        )
    return recent is not None


async def _best_effort_mark_fired(
    redis_client: aioredis.Redis,
    user_id: int,
    address: str,
    candidate: AlertCandidate,
    ttl_seconds: int,
) -> None:
    try:
        await dedup_mod.mark_fired(
            redis_client, user_id, address, candidate.alert_type, ttl_seconds
        )
    except Exception as exc:  # noqa: BLE001 — best-effort
        _log.warning(
            "alerts.dedup.mark_failed",
            address=_redact(address),
            user_id=user_id,
            alert_type=candidate.alert_type.value,
            error=str(exc),
        )


async def _process_candidate(
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    redis_client: aioredis.Redis,
    dispatcher: TelegramDispatcher,
    settings: Settings,
    user: User,
    subscription: Subscription,
    token: Token | None,
    candidate: AlertCandidate,
    now_utc: datetime,
) -> None:
    address = subscription.token_address
    ttl_seconds = dedup_mod.ttl_for_alert_type(candidate.alert_type, settings)

    if await _dedup_skip_with_fallback(
        redis_client,
        sessionmaker,
        subscription.id,
        user.id,
        address,
        candidate,
        ttl_seconds,
    ):
        _log.debug(
            "alerts.dedup.skip",
            address=_redact(address),
            user_id=user.id,
            alert_type=candidate.alert_type.value,
        )
        return

    reason = is_suppressed(user, subscription, now_utc)

    alert_id = await _persist_alert(sessionmaker, subscription.id, candidate)
    await _best_effort_mark_fired(redis_client, user.id, address, candidate, ttl_seconds)

    if reason is not None:
        await _mark_failed(sessionmaker, alert_id, f"suppressed: {reason}")
        _log.info(
            "alerts.suppressed",
            address=_redact(address),
            user_id=user.id,
            alert_type=candidate.alert_type.value,
            reason=reason,
        )
        return

    text = format_alert_text(candidate, subscription, token)
    try:
        await dispatcher.send_alert(user.chat_id, text)
    except Exception as exc:  # noqa: BLE001 — already retried inside dispatcher
        await _mark_failed(sessionmaker, alert_id, str(exc))
        _log.warning(
            "alerts.dispatch.failed",
            address=_redact(address),
            user_id=user.id,
            alert_type=candidate.alert_type.value,
            error=str(exc),
        )
        return

    await _mark_delivered(sessionmaker, alert_id)
    _log.info(
        "alerts.dispatched",
        address=_redact(address),
        user_id=user.id,
        alert_type=candidate.alert_type.value,
    )


async def _process_event(
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    redis_client: aioredis.Redis,
    dispatcher: TelegramDispatcher,
    settings: Settings,
    payload: dict[str, Any],
) -> None:
    address = payload.get("address")
    if not isinstance(address, str):
        _log.warning("alerts.event.bad_address", payload=payload)
        return

    raw_ts = payload.get("ts")
    try:
        event_ts = datetime.fromisoformat(raw_ts) if isinstance(raw_ts, str) else datetime.now(UTC)
    except ValueError:
        event_ts = datetime.now(UTC)
    if event_ts.tzinfo is None:
        event_ts = event_ts.replace(tzinfo=UTC)

    current_mc = _decimal_or_none(payload.get("market_cap_usd"))
    current_vol = _decimal_or_none(payload.get("volume_5m_usd"))

    async with sessionmaker() as session:
        subs = await SubscriptionRepository(session).get_active_by_token(address)
        if not subs:
            return
        users = await _load_users(session, {s.user_id for s in subs})
        token = await _load_token(session, address)
        history = await _load_volume_history(session, address, settings, event_ts)

    now_utc = datetime.now(UTC)
    for sub in subs:
        user = users.get(sub.user_id)
        if user is None:
            _log.warning(
                "alerts.user.missing",
                subscription_id=sub.id,
                user_id=sub.user_id,
            )
            continue

        try:
            candidates: list[AlertCandidate] = list(
                evaluate_thresholds(
                    current_market_cap=current_mc,
                    baseline_market_cap=sub.baseline_market_cap,
                    growth_threshold_pct=sub.growth_threshold_pct,
                    stoploss_threshold_pct=sub.stoploss_threshold_pct,
                    warning_buffer_pct=sub.warning_buffer_pct,
                )
            )
            spike = evaluate_volume_spike(
                current_volume=current_vol,
                history=history,
                k=sub.volume_spike_k,
                min_samples=settings.VOLUME_SPIKE_MIN_SAMPLES,
                current_market_cap=current_mc,
            )
            if spike is not None:
                candidates.append(spike)

            for candidate in candidates:
                await _process_candidate(
                    sessionmaker=sessionmaker,
                    redis_client=redis_client,
                    dispatcher=dispatcher,
                    settings=settings,
                    user=user,
                    subscription=sub,
                    token=token,
                    candidate=candidate,
                    now_utc=now_utc,
                )
        except Exception as exc:  # noqa: BLE001 — never let one sub abort the loop
            _log.exception(
                "alerts.per_sub.failed",
                subscription_id=sub.id,
                address=_redact(address),
                error=str(exc),
            )


async def run(
    sessionmaker: async_sessionmaker[AsyncSession],
    redis_client: aioredis.Redis,
    dispatcher: TelegramDispatcher,
    stop_event: asyncio.Event,
) -> None:
    """Run the subscriber loop until ``stop_event`` is set.

    ``redis_client`` is the long-running ``get_redis()`` singleton; the
    pubsub connection is opened on top of it. SUBSCRIBE confirmations
    are drained off the stream before regular consumption begins (see
    Session 5 lesson on pub-sub backpressure).
    """
    settings = get_settings()
    pubsub = redis_client.pubsub()
    try:
        await pubsub.subscribe(PRICE_UPDATED_CHANNEL)
        # Drain SUBSCRIBE confirmation frame(s).
        for _ in range(10):
            msg = await pubsub.get_message(ignore_subscribe_messages=False, timeout=0.1)
            if msg and msg.get("type") == "subscribe":
                break
        _log.info("alerts.subscriber.ready", channel=PRICE_UPDATED_CHANNEL)

        while not stop_event.is_set():
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
            if msg is None:
                continue
            data = msg.get("data")
            if not isinstance(data, bytes | bytearray):
                continue
            try:
                payload = json.loads(data)
            except json.JSONDecodeError as exc:
                _log.warning("alerts.event.bad_json", error=str(exc))
                continue

            try:
                await _process_event(
                    sessionmaker=sessionmaker,
                    redis_client=redis_client,
                    dispatcher=dispatcher,
                    settings=settings,
                    payload=payload,
                )
            except Exception as exc:  # noqa: BLE001 — keep consuming
                _log.exception(
                    "alerts.message.failed",
                    error=str(exc),
                )
    finally:
        try:
            await pubsub.aclose()  # type: ignore[no-untyped-call]
        except Exception as exc:  # noqa: BLE001 — best-effort
            _log.warning("alerts.pubsub.close_failed", error=str(exc))
