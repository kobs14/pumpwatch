"""Periodic reconciliation of recently-failed alert dispatches.

The live subscriber (``alerts/subscriber.py``) persists a row to
``alerts_sent`` *before* attempting Telegram dispatch, so a failed send
leaves a row with ``delivered=False`` and ``delivery_error`` set. This
reconciler walks the most recent failed rows and gives them one more
chance — useful for transient Telegram outages, rate-limit blips, or
chat-id glitches that resolve on their own.

Invariants (ADR #17 + Session 7 design):

* **Never re-dispatch suppressed rows.** ``delivery_error`` starting
  with ``"suppressed:"`` is intentional; replaying those on unmute is
  the bug we explicitly designed against.
* **Capped retries.** Each row has a ``dispatch_attempts`` counter
  (default 1, bumped on each reconciler call). The SQL filter and the
  bookkeeping cap together ensure no row is touched more than
  ``ALERT_RECONCILE_MAX_ATTEMPTS + 1`` times total.
* **Per-step transactions.** Same shape as the live subscriber: load
  candidates in one read session, then re-load + update each row in
  its own transaction. Reconciler commits each row independently so a
  Telegram outage on one user doesn't roll back another's flip-to-
  delivered.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pumpwatch.alerts.detectors import AlertCandidate
from pumpwatch.alerts.dispatcher import (
    TelegramDispatcher,
    build_dispatcher,
    format_alert_text,
    shutdown_dispatcher,
)
from pumpwatch.alerts.suppression import is_suppressed
from pumpwatch.config import get_settings
from pumpwatch.db.enums import AlertType
from pumpwatch.db.models import AlertSent, Subscription, Token, User
from pumpwatch.db.repos.alert import AlertRepository
from pumpwatch.db.session import get_sessionmaker
from pumpwatch.logging import get_logger

_log = get_logger(__name__)


async def _reconcile_row(
    sessionmaker: async_sessionmaker[AsyncSession],
    dispatcher: TelegramDispatcher,
    row: AlertSent,
    counts: dict[str, int],
) -> None:
    """Re-attempt one alert row. All branches update ``counts``."""
    counts["candidates"] += 1

    # Defensive double-check beyond the SQL filter (ADR #17 — never
    # re-dispatch suppressed rows, even if a misconfigured row slips
    # through the filter).
    if row.delivery_error and row.delivery_error.startswith("suppressed:"):
        return

    async with sessionmaker() as session:
        sub = (
            await session.execute(
                select(Subscription).where(Subscription.id == row.subscription_id)
            )
        ).scalar_one_or_none()
        user: User | None = None
        token: Token | None = None
        if sub is not None:
            user = (
                await session.execute(select(User).where(User.id == sub.user_id))
            ).scalar_one_or_none()
            token = (
                await session.execute(select(Token).where(Token.address == sub.token_address))
            ).scalar_one_or_none()

    if sub is None or user is None:
        async with sessionmaker() as session, session.begin():
            await AlertRepository(session).mark_redispatched(
                row.id, success=False, error="subscription or user removed"
            )
        counts["failed_again"] += 1
        return

    reason = is_suppressed(user, sub, datetime.now(UTC))
    if reason is not None:
        # Newly suppressed since the row was created (e.g. the user
        # muted themselves between original failure and reconciliation).
        # ADR #17: still mark, never deliver.
        async with sessionmaker() as session, session.begin():
            await AlertRepository(session).mark_redispatched(
                row.id, success=False, error=f"suppressed: {reason}"
            )
        counts["suppressed_now"] += 1
        return

    candidate = AlertCandidate(
        alert_type=AlertType(row.alert_type),
        market_cap=row.triggered_at_market_cap,
        payload=row.payload_json or {},
    )
    text = format_alert_text(candidate, sub, token)

    try:
        await dispatcher.send_alert(user.chat_id, text)
    except Exception as exc:  # noqa: BLE001 — already retried inside dispatcher
        async with sessionmaker() as session, session.begin():
            await AlertRepository(session).mark_redispatched(row.id, success=False, error=str(exc))
        counts["failed_again"] += 1
        _log.warning(
            "alerts.reconcile.dispatch_failed",
            alert_id=row.id,
            user_id=user.id,
            error=str(exc),
        )
        return

    async with sessionmaker() as session, session.begin():
        await AlertRepository(session).mark_redispatched(row.id, success=True, error=None)
    counts["redelivered"] += 1
    _log.info(
        "alerts.reconcile.redelivered",
        alert_id=row.id,
        user_id=user.id,
        alert_type=row.alert_type,
    )


async def _reconcile_async() -> dict[str, int]:
    """Sweep recently-failed alerts and re-attempt dispatch.

    Returns counts: ``candidates`` (rows considered), ``redelivered``
    (now ``delivered=True``), ``failed_again`` (still failing), and
    ``suppressed_now`` (newly suppressed; ADR #17 — not delivered).
    """
    settings = get_settings()
    sessionmaker = get_sessionmaker()
    counts = {"candidates": 0, "redelivered": 0, "failed_again": 0, "suppressed_now": 0}

    async with sessionmaker() as session:
        rows = await AlertRepository(session).list_recently_failed(
            window_seconds=settings.ALERT_RECONCILE_WINDOW_SECONDS,
            max_attempts=settings.ALERT_RECONCILE_MAX_ATTEMPTS,
        )

    if not rows:
        return counts

    dispatcher: TelegramDispatcher | None = None
    try:
        try:
            dispatcher = await build_dispatcher(settings.TELEGRAM_BOT_TOKEN, settings)
        except Exception as exc:  # noqa: BLE001 — best-effort run
            _log.warning("alerts.reconcile.dispatcher.init_failed", error=str(exc))
            return counts

        for row in rows:
            try:
                await _reconcile_row(sessionmaker, dispatcher, row, counts)
            except Exception as exc:  # noqa: BLE001 — never let one row abort the sweep
                _log.exception(
                    "alerts.reconcile.row_failed",
                    alert_id=row.id,
                    error=str(exc),
                )
    finally:
        if dispatcher is not None:
            await shutdown_dispatcher(dispatcher)

    _log.info("alerts.reconcile.done", **counts)
    return counts
