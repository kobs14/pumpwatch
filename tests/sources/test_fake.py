"""Tests for FakePriceDataSource."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from pumpwatch.sources.base import TokenSnapshot
from pumpwatch.sources.exceptions import PumpFunUnavailableError
from pumpwatch.sources.fake import FakePriceDataSource, make_fake_source


def _snap(address: str, market_cap: str) -> TokenSnapshot:
    return TokenSnapshot(
        address=address,
        symbol="TEST",
        name="Test Token",
        market_cap_usd=Decimal(market_cap),
        price_usd=None,
        volume_5m_usd=None,
        liquidity_usd=None,
        holder_count=None,
        source="fake",
        fetched_at=datetime.now(UTC),
    )


async def test_fetch_one_returns_scripted_snapshot() -> None:
    source = make_fake_source({"abc": [_snap("abc", "1000")]})
    result = await source.fetch_one("abc")
    assert result is not None
    assert result.market_cap_usd == Decimal("1000")


async def test_fetch_one_advances_cursor_then_holds_last() -> None:
    source = make_fake_source(
        {"abc": [_snap("abc", "1000"), _snap("abc", "2000"), _snap("abc", "3000")]}
    )
    v1 = await source.fetch_one("abc")
    v2 = await source.fetch_one("abc")
    v3 = await source.fetch_one("abc")
    v4 = await source.fetch_one("abc")
    assert v1 is not None and v1.market_cap_usd == Decimal("1000")
    assert v2 is not None and v2.market_cap_usd == Decimal("2000")
    assert v3 is not None and v3.market_cap_usd == Decimal("3000")
    # Exhausted — last value is returned repeatedly.
    assert v4 is not None and v4.market_cap_usd == Decimal("3000")


async def test_fetch_one_unknown_address_returns_none() -> None:
    source = make_fake_source({"abc": [_snap("abc", "1")]})
    assert await source.fetch_one("xyz") is None


async def test_fetch_one_injected_failure() -> None:
    source = FakePriceDataSource(
        snapshots={"abc": [_snap("abc", "1")]},
        fail_addresses={"abc"},
    )
    with pytest.raises(PumpFunUnavailableError):
        await source.fetch_one("abc")


async def test_fetch_one_respects_latency() -> None:
    source = FakePriceDataSource(
        snapshots={"abc": [_snap("abc", "1")]},
        latency_ms=50,
    )
    start = time.perf_counter()
    await source.fetch_one("abc")
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert elapsed_ms >= 40  # generous tolerance for timer granularity


async def test_fetch_batch_aggregates_and_drops_failures() -> None:
    source = FakePriceDataSource(
        snapshots={
            "ok1": [_snap("ok1", "10")],
            "ok2": [_snap("ok2", "20")],
            "bad": [_snap("bad", "30")],
        },
        fail_addresses={"bad"},
    )
    results = await source.fetch_batch(["ok1", "ok2", "bad", "missing"])
    assert set(results.keys()) == {"ok1", "ok2"}
    assert results["ok1"].market_cap_usd == Decimal("10")
    assert results["ok2"].market_cap_usd == Decimal("20")


async def test_close_is_noop_and_idempotent() -> None:
    source = make_fake_source({})
    await source.close()
    await source.close()


async def test_fetch_batch_is_concurrent() -> None:
    """Five calls at 50ms latency finish well under 250ms when run concurrently."""
    source = FakePriceDataSource(
        snapshots={f"a{i}": [_snap(f"a{i}", str(i))] for i in range(5)},
        latency_ms=50,
    )
    start = time.perf_counter()
    await source.fetch_batch([f"a{i}" for i in range(5)])
    elapsed_ms = (time.perf_counter() - start) * 1000
    # Concurrent gather finishes in ~50ms; sequential would take ~250ms.
    assert elapsed_ms < 200
    assert elapsed_ms >= 40
