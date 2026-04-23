"""Tests for PriceSnapshotRepository."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pumpwatch.db.models import PriceSnapshot, Token
from pumpwatch.db.repos import PriceSnapshotRepository, TokenRepository


async def _seed_token(db_session: AsyncSession, address: str) -> None:
    await TokenRepository(db_session).upsert(address, symbol="T")


def _snap(address: str, market_cap: str, ts: datetime) -> PriceSnapshot:
    return PriceSnapshot(
        token_address=address,
        market_cap_usd=Decimal(market_cap),
        ts=ts,
    )


async def test_insert_and_latest(db_session: AsyncSession) -> None:
    await _seed_token(db_session, "tok_ps_a")
    repo = PriceSnapshotRepository(db_session)

    older = _snap("tok_ps_a", "1000", datetime.now(UTC) - timedelta(minutes=5))
    newer = _snap("tok_ps_a", "2000", datetime.now(UTC))
    await repo.insert(older)
    await repo.insert(newer)

    latest = await repo.latest_for_token("tok_ps_a")
    assert latest is not None
    assert latest.market_cap_usd == Decimal("2000")


async def test_insert_many_bulk(db_session: AsyncSession) -> None:
    await _seed_token(db_session, "tok_ps_b")
    repo = PriceSnapshotRepository(db_session)

    now = datetime.now(UTC)
    batch = [_snap("tok_ps_b", str(i * 10), now + timedelta(seconds=i)) for i in range(5)]
    await repo.insert_many(batch)

    count = (
        await db_session.execute(
            select(func.count())
            .select_from(PriceSnapshot)
            .where(PriceSnapshot.token_address == "tok_ps_b")
        )
    ).scalar_one()
    assert count == 5


async def test_insert_many_empty_is_noop(db_session: AsyncSession) -> None:
    repo = PriceSnapshotRepository(db_session)
    await repo.insert_many([])


async def test_history_for_token_slices_by_time(db_session: AsyncSession) -> None:
    await _seed_token(db_session, "tok_ps_c")
    repo = PriceSnapshotRepository(db_session)

    now = datetime.now(UTC)
    too_old = _snap("tok_ps_c", "1", now - timedelta(hours=2))
    in_window_1 = _snap("tok_ps_c", "2", now - timedelta(minutes=10))
    in_window_2 = _snap("tok_ps_c", "3", now - timedelta(minutes=5))
    await repo.insert_many([too_old, in_window_1, in_window_2])

    since = now - timedelta(minutes=30)
    history = await repo.history_for_token("tok_ps_c", since=since)
    assert [s.market_cap_usd for s in history] == [Decimal("3"), Decimal("2")]


async def test_latest_for_unknown_token_is_none(db_session: AsyncSession) -> None:
    repo = PriceSnapshotRepository(db_session)
    assert await repo.latest_for_token("never_seen") is None


async def test_cascade_delete_on_token(db_session: AsyncSession) -> None:
    await _seed_token(db_session, "tok_ps_cascade")
    repo = PriceSnapshotRepository(db_session)
    await repo.insert(_snap("tok_ps_cascade", "1", datetime.now(UTC)))

    token = await db_session.get(Token, "tok_ps_cascade")
    assert token is not None
    await db_session.delete(token)
    await db_session.flush()

    remaining = (
        await db_session.execute(
            select(func.count())
            .select_from(PriceSnapshot)
            .where(PriceSnapshot.token_address == "tok_ps_cascade")
        )
    ).scalar_one()
    assert remaining == 0
