"""End-to-end contract test: fake source → repository → database → readback."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from pumpwatch.db.models import PriceSnapshot
from pumpwatch.db.repos import PriceSnapshotRepository, TokenRepository
from pumpwatch.sources.base import TokenSnapshot
from pumpwatch.sources.fake import make_fake_source


def _snapshot(address: str, mcap: str) -> TokenSnapshot:
    return TokenSnapshot(
        address=address,
        symbol=address.upper(),
        name=f"Token {address}",
        market_cap_usd=Decimal(mcap),
        price_usd=Decimal("0.00000001234"),
        volume_5m_usd=Decimal("42.5000"),
        liquidity_usd=Decimal("9999.9999"),
        holder_count=123,
        source="fake",
        fetched_at=datetime.now(UTC),
    )


async def test_fake_source_persisted_and_read_back(db_session: AsyncSession) -> None:
    addresses = ["tokA", "tokB", "tokC", "tokD", "tokE"]
    market_caps = ["100.1234", "200.5678", "300.9012", "400.3456", "500.7890"]

    tokens = TokenRepository(db_session)
    for addr in addresses:
        await tokens.upsert(addr, symbol=addr.upper())

    source = make_fake_source(
        {addr: [_snapshot(addr, mcap)] for addr, mcap in zip(addresses, market_caps, strict=True)}
    )
    fetched = await source.fetch_batch(addresses)
    assert set(fetched.keys()) == set(addresses)

    repo = PriceSnapshotRepository(db_session)
    rows = [
        PriceSnapshot(
            token_address=snap.address,
            market_cap_usd=snap.market_cap_usd,
            price_usd=snap.price_usd,
            volume_5m_usd=snap.volume_5m_usd,
            liquidity_usd=snap.liquidity_usd,
            holder_count=snap.holder_count,
            source=snap.source,
            ts=snap.fetched_at,
        )
        for snap in fetched.values()
    ]
    await repo.insert_many(rows)

    # Read back and assert Decimal precision survives the round-trip.
    since = datetime.now(UTC) - timedelta(minutes=5)
    for addr, expected_mcap in zip(addresses, market_caps, strict=True):
        history = await repo.history_for_token(addr, since=since)
        assert len(history) == 1
        persisted = history[0]
        assert persisted.market_cap_usd == Decimal(expected_mcap)
        assert persisted.price_usd == Decimal("0.00000001234")
        assert persisted.liquidity_usd == Decimal("9999.9999")
        assert persisted.holder_count == 123
        assert persisted.source == "fake"
