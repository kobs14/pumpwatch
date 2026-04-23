"""User repository — reads and writes against the ``users`` table."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pumpwatch.db.models import User


class UserRepository:
    """Encapsulates all SQL against the ``users`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        """Return the user for ``telegram_id``, or ``None`` if not onboarded."""
        stmt = select(User).where(User.telegram_id == telegram_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert_from_telegram(
        self,
        telegram_id: int,
        username: str | None,
        language_code: str | None,
    ) -> User:
        """Insert-or-update a user keyed by Telegram ID.

        Username/language may change on every update from Telegram so we refresh
        them. Returns the persisted ``User`` row.
        """
        values: dict[str, Any] = {
            "telegram_id": telegram_id,
            "telegram_username": username,
        }
        if language_code is not None:
            values["language_code"] = language_code

        stmt = (
            insert(User)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["telegram_id"],
                set_={k: v for k, v in values.items() if k != "telegram_id"},
            )
            .returning(User)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.scalar_one()

    async def update_settings(self, user_id: int, **fields: Any) -> User:
        """Apply ``fields`` to the user identified by ``user_id`` and return it."""
        stmt = select(User).where(User.id == user_id)
        user = (await self._session.execute(stmt)).scalar_one()
        for key, value in fields.items():
            setattr(user, key, value)
        await self._session.flush()
        return user
