"""Tests for PumpFunClient using aioresponses to mock the HTTP layer."""

from __future__ import annotations

import time
from decimal import Decimal

import aiohttp
import pytest
from aioresponses import aioresponses

from pumpwatch.config import Settings, get_settings
from pumpwatch.sources.exceptions import PumpFunUnavailableError
from pumpwatch.sources.pumpfun import PumpFunClient, _parse_snapshot


def _test_settings(**overrides: object) -> Settings:
    """Build a Settings instance with the current env plus overrides."""
    base = get_settings().model_dump()
    base.update(overrides)
    return Settings.model_validate(base)


def _coin_url(address: str) -> str:
    return f"{get_settings().PUMPFUN_BASE_URL}/coins/{address}"


async def test_parse_snapshot_maps_expected_fields() -> None:
    payload = {
        "symbol": "DOG",
        "name": "Dog Coin",
        "usd_market_cap": "123456.789",
        "price_usd": "0.00000001234",
        "volume_5m": "5000.12",
        "liquidity_usd": "42000.00",
        "holder_count": 1234,
    }
    snap = _parse_snapshot("addr1", payload)
    assert snap.address == "addr1"
    assert snap.symbol == "DOG"
    assert snap.name == "Dog Coin"
    assert snap.market_cap_usd == Decimal("123456.789")
    assert snap.price_usd == Decimal("0.00000001234")
    assert snap.volume_5m_usd == Decimal("5000.12")
    assert snap.liquidity_usd == Decimal("42000.00")
    assert snap.holder_count == 1234
    assert snap.source == "pumpfun"


async def test_parse_snapshot_missing_fields_become_none() -> None:
    snap = _parse_snapshot("addr2", {})
    assert snap.market_cap_usd is None
    assert snap.price_usd is None
    assert snap.volume_5m_usd is None
    assert snap.liquidity_usd is None
    assert snap.holder_count is None


async def test_fetch_one_happy_path() -> None:
    client = PumpFunClient()
    with aioresponses() as m:
        m.get(
            _coin_url("good"),
            status=200,
            payload={"symbol": "G", "name": "Good", "usd_market_cap": "100.50"},
        )
        async with client:
            snap = await client.fetch_one("good")
    assert snap is not None
    assert snap.symbol == "G"
    assert snap.market_cap_usd == Decimal("100.50")


async def test_fetch_one_404_returns_none() -> None:
    client = PumpFunClient()
    with aioresponses() as m:
        m.get(_coin_url("nope"), status=404)
        async with client:
            result = await client.fetch_one("nope")
    assert result is None


async def test_fetch_one_retries_503_then_succeeds() -> None:
    client = PumpFunClient(_test_settings(PUMPFUN_MAX_RETRY_ATTEMPTS=3))
    with aioresponses() as m:
        m.get(_coin_url("flaky"), status=503)
        m.get(_coin_url("flaky"), status=503)
        m.get(
            _coin_url("flaky"),
            status=200,
            payload={"symbol": "FLK", "usd_market_cap": "1"},
        )
        async with client:
            snap = await client.fetch_one("flaky")
    assert snap is not None
    assert snap.symbol == "FLK"


async def test_fetch_one_exhausted_retries_raises() -> None:
    client = PumpFunClient(_test_settings(PUMPFUN_MAX_RETRY_ATTEMPTS=3))
    with aioresponses() as m:
        for _ in range(3):
            m.get(_coin_url("dead"), status=503)
        async with client:
            with pytest.raises(PumpFunUnavailableError):
                await client.fetch_one("dead")


async def test_fetch_one_timeout_raises_after_retries() -> None:
    client = PumpFunClient(_test_settings(PUMPFUN_MAX_RETRY_ATTEMPTS=2))
    with aioresponses() as m:
        for _ in range(2):
            m.get(_coin_url("slow"), exception=TimeoutError("simulated timeout"))
        async with client:
            with pytest.raises(PumpFunUnavailableError):
                await client.fetch_one("slow")


async def test_fetch_one_client_error_is_retried_then_raises() -> None:
    client = PumpFunClient(_test_settings(PUMPFUN_MAX_RETRY_ATTEMPTS=2))
    with aioresponses() as m:
        for _ in range(2):
            m.get(
                _coin_url("broken"),
                exception=aiohttp.ClientConnectionError("reset"),
            )
        async with client:
            with pytest.raises(PumpFunUnavailableError):
                await client.fetch_one("broken")


async def test_rate_limiter_engages_on_batch() -> None:
    """16 requests at 8 req/sec should take at least ~1s of wall clock."""
    client = PumpFunClient(_test_settings(PUMPFUN_RATE_LIMIT_PER_SEC=8, PUMPFUN_MAX_BATCH_SIZE=16))
    addresses = [f"addr{i}" for i in range(16)]
    with aioresponses() as m:
        for a in addresses:
            m.get(
                _coin_url(a),
                status=200,
                payload={"symbol": "X", "usd_market_cap": "1"},
            )
        async with client:
            start = time.perf_counter()
            results = await client.fetch_batch(addresses)
            elapsed = time.perf_counter() - start
    assert len(results) == 16
    assert elapsed >= 1.0, f"rate limiter not engaged (elapsed={elapsed:.3f}s)"
    assert elapsed < 5.0, f"suspiciously slow (elapsed={elapsed:.3f}s)"


async def test_close_is_idempotent() -> None:
    client = PumpFunClient()
    async with client:
        pass
    await client.close()
    await client.close()


async def test_fetch_batch_skips_failures() -> None:
    client = PumpFunClient(_test_settings(PUMPFUN_MAX_RETRY_ATTEMPTS=1))
    with aioresponses() as m:
        m.get(
            _coin_url("ok"),
            status=200,
            payload={"symbol": "OK", "usd_market_cap": "100"},
        )
        m.get(_coin_url("miss"), status=404)
        m.get(_coin_url("boom"), status=503)
        async with client:
            results = await client.fetch_batch(["ok", "miss", "boom"])
    assert set(results.keys()) == {"ok"}
