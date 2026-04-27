"""Tests for DexScreenerClient using aioresponses to mock the HTTP layer."""

from __future__ import annotations

from decimal import Decimal

import aiohttp
import pytest
from aioresponses import aioresponses
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from pumpwatch.config import Settings, get_settings
from pumpwatch.db.models import ApiCallLog
from pumpwatch.sources.dexscreener import (
    DexScreenerClient,
    _parse_pair,
    _select_pair,
)
from pumpwatch.sources.exceptions import DexScreenerUnavailableError


def _test_settings(**overrides: object) -> Settings:
    """Build a Settings instance with the current env plus overrides."""
    base = get_settings().model_dump()
    base.update(overrides)
    return Settings.model_validate(base)


def _tokens_url(addresses: str) -> str:
    return f"{get_settings().DEXSCREENER_BASE_URL}/latest/dex/tokens/{addresses}"


def _pair(
    address: str,
    *,
    chain: str = "solana",
    liquidity_usd: str = "100000",
    price_usd: str = "0.0001234",
    market_cap: str = "1234567",
    volume_m5: str = "5000.5",
    symbol: str = "X",
    name: str = "Token X",
) -> dict[str, object]:
    return {
        "chainId": chain,
        "dexId": "raydium",
        "baseToken": {"address": address, "name": name, "symbol": symbol},
        "priceUsd": price_usd,
        "marketCap": market_cap,
        "liquidity": {"usd": liquidity_usd},
        "volume": {"m5": volume_m5, "h24": "100000"},
    }


# ---- Pure parsers -----------------------------------------------------


async def test_select_pair_picks_highest_liquidity_solana_pair() -> None:
    pairs = [
        _pair("addr1", liquidity_usd="100"),
        _pair("addr1", liquidity_usd="9999.99"),
        _pair("addr1", chain="ethereum", liquidity_usd="1000000"),  # wrong chain
        _pair("addr2", liquidity_usd="42"),  # different token
    ]
    chosen = _select_pair(pairs, "addr1")
    assert chosen is not None
    assert chosen["liquidity"]["usd"] == "9999.99"


async def test_select_pair_returns_none_when_no_solana_match() -> None:
    pairs = [_pair("addr1", chain="ethereum")]
    assert _select_pair(pairs, "addr1") is None


async def test_select_pair_handles_malformed_payload() -> None:
    assert _select_pair(None, "addr1") is None
    assert _select_pair("nope", "addr1") is None
    assert _select_pair([{"chainId": "solana"}, "garbage"], "addr1") is None


async def test_parse_pair_maps_expected_fields() -> None:
    pair = _pair(
        "addrA",
        symbol="DOG",
        name="Dog",
        liquidity_usd="42000.0",
        price_usd="0.0000123",
        market_cap="123456",
        volume_m5="500.5",
    )
    snap = _parse_pair("addrA", pair)
    assert snap.symbol == "DOG"
    assert snap.name == "Dog"
    assert snap.market_cap_usd == Decimal("123456")
    assert snap.price_usd == Decimal("0.0000123")
    assert snap.volume_5m_usd == Decimal("500.5")
    assert snap.liquidity_usd == Decimal("42000.0")
    assert snap.holder_count is None  # DexScreener does not expose holder count
    assert snap.source == "dexscreener"


async def test_parse_pair_falls_back_to_fdv_when_market_cap_missing() -> None:
    pair = {
        "chainId": "solana",
        "baseToken": {"address": "x", "symbol": "X", "name": "X"},
        "priceUsd": "1",
        "fdv": "999",
        "liquidity": {"usd": "100"},
        "volume": {},
    }
    snap = _parse_pair("x", pair)
    assert snap.market_cap_usd == Decimal("999")
    assert snap.volume_5m_usd is None  # m5 absent → None


# ---- HTTP layer --------------------------------------------------------


async def test_fetch_one_happy_path() -> None:
    client = DexScreenerClient()
    with aioresponses() as m:
        m.get(
            _tokens_url("good"),
            status=200,
            payload={"pairs": [_pair("good", symbol="G", liquidity_usd="500")]},
        )
        async with client:
            snap = await client.fetch_one("good")
    assert snap is not None
    assert snap.symbol == "G"
    assert snap.liquidity_usd == Decimal("500")


async def test_fetch_one_no_solana_pair_returns_none() -> None:
    client = DexScreenerClient()
    with aioresponses() as m:
        m.get(
            _tokens_url("ethonly"),
            status=200,
            payload={"pairs": [_pair("ethonly", chain="ethereum")]},
        )
        async with client:
            snap = await client.fetch_one("ethonly")
    assert snap is None


async def test_fetch_one_404_returns_none() -> None:
    client = DexScreenerClient()
    with aioresponses() as m:
        m.get(_tokens_url("nope"), status=404)
        async with client:
            assert await client.fetch_one("nope") is None


async def test_fetch_one_retries_503_then_succeeds() -> None:
    client = DexScreenerClient(_test_settings(DEXSCREENER_MAX_RETRY_ATTEMPTS=3))
    with aioresponses() as m:
        m.get(_tokens_url("flaky"), status=503)
        m.get(_tokens_url("flaky"), status=503)
        m.get(
            _tokens_url("flaky"),
            status=200,
            payload={"pairs": [_pair("flaky", symbol="FLK")]},
        )
        async with client:
            snap = await client.fetch_one("flaky")
    assert snap is not None
    assert snap.symbol == "FLK"


async def test_fetch_one_exhausted_retries_raises() -> None:
    client = DexScreenerClient(_test_settings(DEXSCREENER_MAX_RETRY_ATTEMPTS=3))
    with aioresponses() as m:
        for _ in range(3):
            m.get(_tokens_url("dead"), status=503)
        async with client:
            with pytest.raises(DexScreenerUnavailableError):
                await client.fetch_one("dead")


async def test_fetch_one_timeout_raises_after_retries() -> None:
    client = DexScreenerClient(_test_settings(DEXSCREENER_MAX_RETRY_ATTEMPTS=2))
    with aioresponses() as m:
        for _ in range(2):
            m.get(_tokens_url("slow"), exception=TimeoutError("simulated"))
        async with client:
            with pytest.raises(DexScreenerUnavailableError):
                await client.fetch_one("slow")


async def test_fetch_one_client_error_retries_then_raises() -> None:
    client = DexScreenerClient(_test_settings(DEXSCREENER_MAX_RETRY_ATTEMPTS=2))
    with aioresponses() as m:
        for _ in range(2):
            m.get(
                _tokens_url("broken"),
                exception=aiohttp.ClientConnectionError("reset"),
            )
        async with client:
            with pytest.raises(DexScreenerUnavailableError):
                await client.fetch_one("broken")


async def test_fetch_batch_chunks_and_dispatches_combined_requests() -> None:
    """fetch_batch joins addresses comma-separated and resolves by baseToken."""
    client = DexScreenerClient(_test_settings(DEXSCREENER_MAX_BATCH_SIZE=2))
    with aioresponses() as m:
        m.get(
            _tokens_url("a,b"),
            status=200,
            payload={"pairs": [_pair("a", symbol="A"), _pair("b", symbol="B")]},
        )
        m.get(
            _tokens_url("c"),
            status=200,
            payload={"pairs": [_pair("c", symbol="C")]},
        )
        async with client:
            results = await client.fetch_batch(["a", "b", "c"])
    assert set(results.keys()) == {"a", "b", "c"}
    assert results["a"].symbol == "A"
    assert results["c"].symbol == "C"


async def test_fetch_batch_skips_chunk_failures_keeps_others() -> None:
    client = DexScreenerClient(
        _test_settings(DEXSCREENER_MAX_BATCH_SIZE=1, DEXSCREENER_MAX_RETRY_ATTEMPTS=1)
    )
    with aioresponses() as m:
        m.get(
            _tokens_url("ok"),
            status=200,
            payload={"pairs": [_pair("ok", symbol="OK")]},
        )
        m.get(_tokens_url("dead"), status=503)
        async with client:
            results = await client.fetch_batch(["ok", "dead"])
    assert set(results.keys()) == {"ok"}


async def test_close_is_idempotent() -> None:
    client = DexScreenerClient()
    async with client:
        pass
    await client.close()
    await client.close()


# ---- api_call_log wiring ---------------------------------------------


async def _truncate_call_log(test_engine: AsyncEngine) -> None:
    async with test_engine.begin() as conn:
        await conn.execute(text("TRUNCATE api_call_log RESTART IDENTITY"))


async def _read_call_logs(sm: async_sessionmaker[AsyncSession]) -> list[ApiCallLog]:
    async with sm() as session:
        result = await session.execute(select(ApiCallLog).order_by(ApiCallLog.id))
        return list(result.scalars().all())


async def test_logs_one_row_on_success(test_engine: AsyncEngine) -> None:
    await _truncate_call_log(test_engine)
    sm = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)
    client = DexScreenerClient(sessionmaker=sm)
    with aioresponses() as m:
        m.get(
            _tokens_url("logme"),
            status=200,
            payload={"pairs": [_pair("logme", symbol="L")]},
        )
        async with client:
            assert await client.fetch_one("logme") is not None

    rows = await _read_call_logs(sm)
    assert len(rows) == 1
    row = rows[0]
    assert row.source == "dexscreener"
    assert row.success is True
    assert row.status_code == 200
    assert row.error is None


async def test_logs_one_row_on_failure(test_engine: AsyncEngine) -> None:
    await _truncate_call_log(test_engine)
    sm = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)
    client = DexScreenerClient(
        _test_settings(DEXSCREENER_MAX_RETRY_ATTEMPTS=2),
        sessionmaker=sm,
    )
    with aioresponses() as m:
        for _ in range(2):
            m.get(_tokens_url("dead"), status=503)
        async with client:
            with pytest.raises(DexScreenerUnavailableError):
                await client.fetch_one("dead")

    rows = await _read_call_logs(sm)
    assert len(rows) == 1
    row = rows[0]
    assert row.success is False
    assert row.status_code == 0
    assert row.error is not None and "dexscreener unavailable" in row.error


async def test_log_failure_does_not_break_data_path(
    test_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sm = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)
    client = DexScreenerClient(sessionmaker=sm)

    async def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated DB outage")

    monkeypatch.setattr(client, "_log_call", _boom)

    with aioresponses() as m:
        m.get(
            _tokens_url("survive"),
            status=200,
            payload={"pairs": [_pair("survive", symbol="S")]},
        )
        async with client:
            snap = await client.fetch_one("survive")
    assert snap is not None
    assert snap.symbol == "S"


async def test_no_log_when_sessionmaker_omitted(test_engine: AsyncEngine) -> None:
    await _truncate_call_log(test_engine)
    sm = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)
    client = DexScreenerClient()
    with aioresponses() as m:
        m.get(
            _tokens_url("silent"),
            status=200,
            payload={"pairs": [_pair("silent", symbol="S")]},
        )
        async with client:
            await client.fetch_one("silent")

    rows = await _read_call_logs(sm)
    assert rows == []
