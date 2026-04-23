"""Tests for UserRepository."""

from __future__ import annotations

from datetime import time

from sqlalchemy.ext.asyncio import AsyncSession

from pumpwatch.db.repos import UserRepository


async def test_upsert_inserts_new_user(db_session: AsyncSession) -> None:
    repo = UserRepository(db_session)
    user = await repo.upsert_from_telegram(telegram_id=111, username="alice", language_code="en")
    assert user.id is not None
    assert user.telegram_id == 111
    assert user.telegram_username == "alice"
    assert user.language_code == "en"


async def test_upsert_updates_existing_user(db_session: AsyncSession) -> None:
    repo = UserRepository(db_session)
    await repo.upsert_from_telegram(telegram_id=222, username="bob", language_code="en")
    updated = await repo.upsert_from_telegram(
        telegram_id=222, username="bob_renamed", language_code="fr"
    )
    assert updated.telegram_username == "bob_renamed"
    assert updated.language_code == "fr"

    # Same row — not a new user.
    again = await repo.get_by_telegram_id(222)
    assert again is not None
    assert again.id == updated.id


async def test_get_by_telegram_id_none_when_missing(db_session: AsyncSession) -> None:
    repo = UserRepository(db_session)
    assert await repo.get_by_telegram_id(999_999) is None


async def test_update_settings_applies_fields(db_session: AsyncSession) -> None:
    repo = UserRepository(db_session)
    user = await repo.upsert_from_telegram(telegram_id=333, username="carol", language_code="en")
    updated = await repo.update_settings(
        user.id,
        quiet_hours_start=time(22, 0),
        quiet_hours_end=time(7, 0),
        timezone="America/Los_Angeles",
    )
    assert updated.quiet_hours_start == time(22, 0)
    assert updated.quiet_hours_end == time(7, 0)
    assert updated.timezone == "America/Los_Angeles"
