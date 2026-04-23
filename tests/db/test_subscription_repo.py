"""Tests for SubscriptionRepository."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pumpwatch.config import get_settings
from pumpwatch.db.enums import Priority, SubscriptionStatus
from pumpwatch.db.models import Subscription
from pumpwatch.db.repos import (
    SubscriptionRepository,
    TokenRepository,
    UserRepository,
)


async def _seed_user_and_token(
    db_session: AsyncSession,
    telegram_id: int,
    address: str,
) -> tuple[int, str]:
    user = await UserRepository(db_session).upsert_from_telegram(
        telegram_id=telegram_id, username="u", language_code="en"
    )
    await TokenRepository(db_session).upsert(address, symbol="T")
    return user.id, address


async def test_create_applies_settings_defaults(db_session: AsyncSession) -> None:
    user_id, addr = await _seed_user_and_token(db_session, 10, "tok_defaults")
    repo = SubscriptionRepository(db_session)

    sub = await repo.create(user_id, addr, Decimal("20.00"), Decimal("-20.00"))
    settings = get_settings()
    assert sub.warning_buffer_pct == settings.WARNING_BUFFER_PCT_DEFAULT
    assert sub.volume_spike_k == settings.VOLUME_SPIKE_K_DEFAULT
    assert sub.priority == Priority.HIGH.value
    assert sub.status == SubscriptionStatus.ACTIVE.value


async def test_create_honors_explicit_overrides(db_session: AsyncSession) -> None:
    user_id, addr = await _seed_user_and_token(db_session, 11, "tok_override")
    repo = SubscriptionRepository(db_session)

    sub = await repo.create(
        user_id,
        addr,
        Decimal("10.00"),
        Decimal("-10.00"),
        baseline_market_cap=Decimal("12345.6789"),
        warning_buffer_pct=Decimal("2.50"),
        volume_spike_k=Decimal("4.00"),
    )
    assert sub.warning_buffer_pct == Decimal("2.50")
    assert sub.volume_spike_k == Decimal("4.00")
    assert sub.baseline_market_cap == Decimal("12345.6789")


async def test_unique_user_token_constraint(db_session: AsyncSession) -> None:
    user_id, addr = await _seed_user_and_token(db_session, 12, "tok_unique")
    repo = SubscriptionRepository(db_session)

    await repo.create(user_id, addr, Decimal("5"), Decimal("-5"))
    with pytest.raises(IntegrityError):
        await repo.create(user_id, addr, Decimal("7"), Decimal("-7"))


async def test_list_for_user_filters_by_status(db_session: AsyncSession) -> None:
    user_id, _ = await _seed_user_and_token(db_session, 13, "tok_list_a")
    await TokenRepository(db_session).upsert("tok_list_b", symbol="B")
    repo = SubscriptionRepository(db_session)

    s1 = await repo.create(user_id, "tok_list_a", Decimal("10"), Decimal("-10"))
    s2 = await repo.create(user_id, "tok_list_b", Decimal("10"), Decimal("-10"))
    await repo.stop(s2.id)

    active = await repo.list_for_user(user_id, status=SubscriptionStatus.ACTIVE)
    stopped = await repo.list_for_user(user_id, status=SubscriptionStatus.STOPPED)
    all_ = await repo.list_for_user(user_id)

    assert [s.id for s in active] == [s1.id]
    assert [s.id for s in stopped] == [s2.id]
    assert {s.id for s in all_} == {s1.id, s2.id}


async def test_get_active_by_token_filters_to_active(db_session: AsyncSession) -> None:
    uid_a, addr = await _seed_user_and_token(db_session, 14, "tok_active_by")
    uid_b = (await UserRepository(db_session).upsert_from_telegram(15, "other", "en")).id
    repo = SubscriptionRepository(db_session)

    s_active = await repo.create(uid_a, addr, Decimal("10"), Decimal("-10"))
    s_stopped = await repo.create(uid_b, addr, Decimal("10"), Decimal("-10"))
    await repo.stop(s_stopped.id)

    active = await repo.get_active_by_token(addr)
    assert [s.id for s in active] == [s_active.id]


async def test_list_by_priority_and_update_priority(db_session: AsyncSession) -> None:
    user_id, addr = await _seed_user_and_token(db_session, 16, "tok_prio")
    repo = SubscriptionRepository(db_session)

    sub = await repo.create(user_id, addr, Decimal("10"), Decimal("-10"))
    assert sub.priority == Priority.HIGH.value

    await repo.update_priority(sub.id, Priority.LOW)
    low_subs = await repo.list_by_priority(Priority.LOW)
    assert any(s.id == sub.id for s in low_subs)

    high_subs = await repo.list_by_priority(Priority.HIGH)
    assert all(s.id != sub.id for s in high_subs)


async def test_cascade_delete_on_user_removes_subscriptions(
    db_session: AsyncSession,
) -> None:
    user_id, addr = await _seed_user_and_token(db_session, 17, "tok_cascade")
    repo = SubscriptionRepository(db_session)
    await repo.create(user_id, addr, Decimal("10"), Decimal("-10"))

    # Deleting the user should cascade via ON DELETE CASCADE.
    user = await UserRepository(db_session).get_by_telegram_id(17)
    assert user is not None
    await db_session.delete(user)
    await db_session.flush()

    remaining = (
        await db_session.execute(
            select(func.count()).select_from(Subscription).where(Subscription.user_id == user_id)
        )
    ).scalar_one()
    assert remaining == 0
