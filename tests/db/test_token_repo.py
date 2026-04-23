"""Tests for TokenRepository."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pumpwatch.db.models import Token
from pumpwatch.db.repos import (
    SubscriptionRepository,
    TokenRepository,
    UserRepository,
)


async def test_upsert_is_idempotent(db_session: AsyncSession) -> None:
    repo = TokenRepository(db_session)
    first = await repo.upsert("addr_upsert", symbol="X", name="Ex")
    second = await repo.upsert("addr_upsert", symbol="X", name="Ex")
    assert first.address == second.address

    count = (
        await db_session.execute(
            select(func.count()).select_from(Token).where(Token.address == "addr_upsert")
        )
    ).scalar_one()
    assert count == 1


async def test_upsert_updates_symbol_and_name(db_session: AsyncSession) -> None:
    repo = TokenRepository(db_session)
    await repo.upsert("addr_update", symbol="OLD", name="Old Name")
    updated = await repo.upsert("addr_update", symbol="NEW", name="New Name")
    assert updated.symbol == "NEW"
    assert updated.name == "New Name"


async def test_get_returns_none_for_missing(db_session: AsyncSession) -> None:
    repo = TokenRepository(db_session)
    assert await repo.get("does_not_exist") is None


async def test_mark_polled_sets_last_polled_at(db_session: AsyncSession) -> None:
    repo = TokenRepository(db_session)
    await repo.upsert("addr_polled", symbol="P")
    token = await repo.get("addr_polled")
    assert token is not None
    assert token.last_polled_at is None

    await repo.mark_polled("addr_polled")
    db_session.expire_all()
    token = await repo.get("addr_polled")
    assert token is not None
    assert token.last_polled_at is not None


async def test_list_active_addresses(db_session: AsyncSession) -> None:
    users = UserRepository(db_session)
    tokens = TokenRepository(db_session)
    subs = SubscriptionRepository(db_session)

    user = await users.upsert_from_telegram(telegram_id=42, username="u", language_code="en")
    await tokens.upsert("active_tok", symbol="A")
    await tokens.upsert("inactive_tok", symbol="I")
    await tokens.upsert("orphan_tok", symbol="O")

    active_sub = await subs.create(user.id, "active_tok", Decimal("20.00"), Decimal("-20.00"))
    inactive_sub = await subs.create(user.id, "inactive_tok", Decimal("20.00"), Decimal("-20.00"))
    await subs.stop(inactive_sub.id)

    _ = active_sub  # referenced to ensure create succeeded
    addresses = await tokens.list_active_addresses()
    assert "active_tok" in addresses
    assert "inactive_tok" not in addresses
    assert "orphan_tok" not in addresses
