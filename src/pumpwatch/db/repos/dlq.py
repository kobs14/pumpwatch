"""Dead-letter-queue repository for ``fetch_token`` failures.

Failures land here only after the Celery retry budget is exhausted. The
``UNIQUE(token_address)`` upsert pattern means re-failures bump
``attempts`` + ``last_seen`` instead of inserting duplicates.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from pumpwatch.db.models import DlqEntry


class DlqRepository:
    """Encapsulates all SQL against the ``dlq_entries`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, token_address: str, error: str) -> None:
        """Insert or bump the row for ``token_address``.

        On conflict we keep the original ``first_seen`` (the migration
        defaults it to ``now()`` only on insert) and update the latest
        ``error``, increment ``attempts`` by one, and refresh ``last_seen``.
        """
        stmt = pg_insert(DlqEntry).values(
            token_address=token_address,
            error=error,
            attempts=1,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_dlq_entries_token_address",
            set_={
                "error": stmt.excluded.error,
                "attempts": DlqEntry.__table__.c.attempts + 1,
                "last_seen": func.now(),
            },
        )
        await self._session.execute(stmt)

    async def count(self) -> int:
        """Return the current DLQ size — backs ``pumpwatch_dlq_size``."""
        result = await self._session.execute(select(func.count()).select_from(DlqEntry))
        return int(result.scalar_one())
