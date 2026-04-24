"""PriceSnapshot repository — time-series reads and bulk inserts."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

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

    async def recent_per_token(
        self,
        token_addresses: Sequence[str],
        limit: int = 20,
        window: timedelta = timedelta(hours=1),
    ) -> dict[str, list[PriceSnapshot]]:
        """Return up to ``limit`` recent snapshots per token, keyed by address.

        One round trip: pulls all snapshots in the last ``window`` for the
        given addresses, then groups in Python and caps each group. The
        time bound prevents pulling years of rows for a long-running token.
        Empty input → empty dict (no query issued).
        """
        if not token_addresses:
            return {}
        cutoff = datetime.now(UTC) - window
        stmt = (
            select(PriceSnapshot)
            .where(PriceSnapshot.token_address.in_(token_addresses))
            .where(PriceSnapshot.ts >= cutoff)
            .order_by(PriceSnapshot.token_address, PriceSnapshot.ts.desc())
        )
        result = await self._session.execute(stmt)
        grouped: dict[str, list[PriceSnapshot]] = {}
        for snap in result.scalars().all():
            bucket = grouped.setdefault(snap.token_address, [])
            if len(bucket) < limit:
                bucket.append(snap)
        return grouped
