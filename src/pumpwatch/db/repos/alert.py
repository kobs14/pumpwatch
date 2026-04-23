"""Alert repository — persists every alert fired by the alert engine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from pumpwatch.db.enums import AlertType
from pumpwatch.db.models import AlertSent


class AlertRepository:
    """Encapsulates all SQL against the ``alerts_sent`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        subscription_id: int,
        alert_type: AlertType,
        market_cap: Decimal | None,
        payload: dict[str, Any],
    ) -> AlertSent:
        """Persist a new alert row (not yet delivered)."""
        alert = AlertSent(
            subscription_id=subscription_id,
            alert_type=alert_type.value,
            triggered_at_market_cap=market_cap,
            payload_json=payload,
        )
        self._session.add(alert)
        await self._session.flush()
        return alert

    async def mark_delivered(self, alert_id: int) -> None:
        """Flag a recorded alert as successfully delivered to Telegram."""
        stmt = (
            update(AlertSent)
            .where(AlertSent.id == alert_id)
            .values(delivered=True, delivery_error=None)
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def mark_delivery_failed(self, alert_id: int, error: str) -> None:
        """Flag a recorded alert as failed and record the error message."""
        stmt = (
            update(AlertSent)
            .where(AlertSent.id == alert_id)
            .values(delivered=False, delivery_error=error)
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def recent_for_subscription(
        self,
        subscription_id: int,
        alert_type: AlertType,
        within_seconds: int,
    ) -> AlertSent | None:
        """Return the most recent matching alert within the window, or ``None``.

        Used by the alert engine as a dedup backstop alongside Redis TTL keys.
        """
        cutoff = datetime.now(UTC) - timedelta(seconds=within_seconds)
        stmt = (
            select(AlertSent)
            .where(AlertSent.subscription_id == subscription_id)
            .where(AlertSent.alert_type == alert_type.value)
            .where(AlertSent.created_at >= cutoff)
            .order_by(AlertSent.created_at.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()
