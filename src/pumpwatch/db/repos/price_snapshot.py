"""PriceSnapshot repository — time-series reads and bulk inserts."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pumpwatch.db.models import PriceSnapshot


class PriceSnapshotRepository:
    """Encapsulates all SQL against the ``price_snapshots`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert(self, snapshot: PriceSnapshot) -> None:
        """Persist a single snapshot."""
        self._session.add(snapshot)
        await self._session.flush()

    async def insert_many(self, snapshots: list[PriceSnapshot]) -> None:
        """Persist a batch of snapshots."""
        if not snapshots:
            return
        self._session.add_all(snapshots)
        await self._session.flush()

    async def latest_for_token(self, token_address: str) -> PriceSnapshot | None:
        """Return the most recent snapshot for a token, or ``None``."""
        stmt = (
            select(PriceSnapshot)
            .where(PriceSnapshot.token_address == token_address)
            .order_by(PriceSnapshot.ts.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def history_for_token(
        self,
        token_address: str,
        since: datetime,
        limit: int = 1000,
    ) -> list[PriceSnapshot]:
        """Return snapshots for ``token_address`` with ``ts >= since``, newest first."""
        stmt = (
            select(PriceSnapshot)
            .where(PriceSnapshot.token_address == token_address)
            .where(PriceSnapshot.ts >= since)
            .order_by(PriceSnapshot.ts.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
