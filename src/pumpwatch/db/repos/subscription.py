"""Subscription repository."""

from __future__ import annotations

from decimal import Decimal
from typing import cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from pumpwatch.config import get_settings
from pumpwatch.db.enums import Priority, SubscriptionStatus
from pumpwatch.db.models import Subscription


class SubscriptionRepository:
    """Encapsulates all SQL against the ``subscriptions`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        user_id: int,
        token_address: str,
        growth_pct: Decimal,
        stoploss_pct: Decimal,
        baseline_market_cap: Decimal | None = None,
        warning_buffer_pct: Decimal | None = None,
        volume_spike_k: Decimal | None = None,
    ) -> Subscription:
        """Create a new subscription. Missing buffer/k values fall back to settings."""
        settings = get_settings()
        sub = Subscription(
            user_id=user_id,
            token_address=token_address,
            growth_threshold_pct=growth_pct,
            stoploss_threshold_pct=stoploss_pct,
            baseline_market_cap=baseline_market_cap,
            warning_buffer_pct=(
                warning_buffer_pct
                if warning_buffer_pct is not None
                else settings.WARNING_BUFFER_PCT_DEFAULT
            ),
            volume_spike_k=(
                volume_spike_k if volume_spike_k is not None else settings.VOLUME_SPIKE_K_DEFAULT
            ),
        )
        self._session.add(sub)
        await self._session.flush()
        return sub

    async def list_for_user(
        self,
        user_id: int,
        status: SubscriptionStatus | None = None,
    ) -> list[Subscription]:
        """Return all subscriptions for a user, optionally filtered by status."""
        stmt = select(Subscription).where(Subscription.user_id == user_id)
        if status is not None:
            stmt = stmt.where(Subscription.status == status.value)
        stmt = stmt.order_by(Subscription.created_at.desc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_active_by_token(self, token_address: str) -> list[Subscription]:
        """Return every active subscription attached to ``token_address``."""
        stmt = (
            select(Subscription)
            .where(Subscription.token_address == token_address)
            .where(Subscription.status == SubscriptionStatus.ACTIVE.value)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_priority(self, priority: Priority) -> list[Subscription]:
        """Return every subscription with the given priority tier."""
        stmt = select(Subscription).where(Subscription.priority == priority.value)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def update_priority(self, subscription_id: int, priority: Priority) -> None:
        """Change the priority tier for one subscription."""
        stmt = (
            update(Subscription)
            .where(Subscription.id == subscription_id)
            .values(priority=priority.value)
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def stop(self, subscription_id: int) -> None:
        """Mark a subscription as ``stopped``."""
        stmt = (
            update(Subscription)
            .where(Subscription.id == subscription_id)
            .values(status=SubscriptionStatus.STOPPED.value)
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def get_by_user_and_token(
        self,
        user_id: int,
        token_address: str,
    ) -> Subscription | None:
        """Return the subscription row for ``(user_id, token_address)`` or ``None``."""
        stmt = (
            select(Subscription)
            .where(Subscription.user_id == user_id)
            .where(Subscription.token_address == token_address)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create_or_update(
        self,
        user_id: int,
        token_address: str,
        growth_pct: Decimal,
        stoploss_pct: Decimal,
    ) -> Subscription:
        """Upsert a subscription's thresholds; reactivate if previously stopped.

        The ``(user_id, token_address)`` pair has a unique constraint, so this
        is the bot's ``/add`` commit path: new token → insert, already-watched
        token → refresh thresholds and flip status back to ``ACTIVE`` if the
        user had previously stopped it. Returns the persisted row.
        """
        existing = await self.get_by_user_and_token(user_id, token_address)
        if existing is None:
            return await self.create(
                user_id=user_id,
                token_address=token_address,
                growth_pct=growth_pct,
                stoploss_pct=stoploss_pct,
            )

        existing.growth_threshold_pct = growth_pct
        existing.stoploss_threshold_pct = stoploss_pct
        existing.status = SubscriptionStatus.ACTIVE
        await self._session.flush()
        return existing

    async def stop_by_user_and_token(
        self,
        user_id: int,
        token_address: str,
    ) -> bool:
        """Soft-deactivate the user's subscription to ``token_address``.

        Returns ``True`` if a row was flipped to ``STOPPED``, ``False`` if no
        matching active/paused subscription existed (caller can use this to
        decide between a "stopped" reply and a "not watching" reply).
        """
        stmt = (
            update(Subscription)
            .where(Subscription.user_id == user_id)
            .where(Subscription.token_address == token_address)
            .where(Subscription.status != SubscriptionStatus.STOPPED.value)
            .values(status=SubscriptionStatus.STOPPED.value)
        )
        result = cast(CursorResult[None], await self._session.execute(stmt))
        await self._session.flush()
        return (result.rowcount or 0) > 0
