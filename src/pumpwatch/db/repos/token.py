"""Token repository — reads and writes against the ``tokens`` table."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pumpwatch.db.enums import SubscriptionStatus
from pumpwatch.db.models import Subscription, Token


class TokenRepository:
    """Encapsulates all SQL against the ``tokens`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, address: str) -> Token | None:
        """Return the token for ``address`` or ``None``."""
        stmt = select(Token).where(Token.address == address)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def upsert(
        self,
        address: str,
        symbol: str | None = None,
        name: str | None = None,
    ) -> Token:
        """Insert-or-update a token by its mint address."""
        values: dict[str, Any] = {"address": address}
        update_values: dict[str, Any] = {}
        if symbol is not None:
            values["symbol"] = symbol
            update_values["symbol"] = symbol
        if name is not None:
            values["name"] = name
            update_values["name"] = name

        insert_stmt = insert(Token).values(**values)
        if update_values:
            stmt = insert_stmt.on_conflict_do_update(index_elements=["address"], set_=update_values)
        else:
            # No non-key fields to update — fall back to a no-op conflict handler.
            stmt = insert_stmt.on_conflict_do_nothing(index_elements=["address"])
        await self._session.execute(stmt)
        await self._session.flush()
        # Re-fetch to return the canonical row (including first_seen_at if inserted).
        fetched = await self.get(address)
        assert fetched is not None  # just upserted
        return fetched

    async def mark_polled(self, address: str) -> None:
        """Set ``last_polled_at = now()`` for the given token."""
        stmt = update(Token).where(Token.address == address).values(last_polled_at=func.now())
        await self._session.execute(stmt)
        await self._session.flush()

    async def list_active_addresses(self) -> list[str]:
        """Return every token address referenced by at least one active subscription."""
        stmt = (
            select(Token.address)
            .join(Subscription, Subscription.token_address == Token.address)
            .where(Subscription.status == SubscriptionStatus.ACTIVE.value)
            .distinct()
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
