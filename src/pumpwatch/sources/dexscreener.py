"""DexScreener public-API client.

Fallback price source per ADR #14. The public endpoint we use is
``GET /latest/dex/tokens/{address1,address2,...}`` which returns a list of
trading pairs across every chain/DEX where the token trades. We filter to
``chainId == "solana"`` and pick the highest-liquidity pair per address.

Mirrors :class:`PumpFunClient` shape (Protocol, retry, ``api_call_log``
writes, best-effort logging) so swapping is a one-env-var change.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from types import TracebackType
from typing import Any, Self

import aiohttp
from aiolimiter import AsyncLimiter
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from pumpwatch.config import Settings, get_settings
from pumpwatch.db.repos.api_call_log import ApiCallLogRepository
from pumpwatch.logging import get_logger
from pumpwatch.observability.metrics import SOURCE_CALLS
from pumpwatch.sources.base import TokenSnapshot
from pumpwatch.sources.exceptions import DexScreenerUnavailableError

_log = get_logger(__name__)


def _redact(address: str) -> str:
    """Truncate a Solana address to ``Abcd...wxyz`` for logs (per CLAUDE.md)."""
    return f"{address[:4]}...{address[-4:]}" if len(address) > 8 else address


def _to_decimal(value: Any) -> Decimal | None:
    """Permissive conversion: strings and numbers → Decimal; anything else → None."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _select_pair(payload_pairs: Any, address: str) -> dict[str, Any] | None:
    """From a DexScreener response, pick the highest-liquidity Solana pair for ``address``.

    Returns ``None`` if the response has no Solana pair for the token.
    """
    if not isinstance(payload_pairs, list):
        return None
    candidates: list[dict[str, Any]] = []
    for pair in payload_pairs:
        if not isinstance(pair, dict):
            continue
        if pair.get("chainId") != "solana":
            continue
        base = pair.get("baseToken")
        if not isinstance(base, dict):
            continue
        if base.get("address") != address:
            continue
        candidates.append(pair)
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda p: _to_decimal((p.get("liquidity") or {}).get("usd")) or Decimal("0"),
    )


def _parse_pair(address: str, pair: dict[str, Any]) -> TokenSnapshot:
    """Map a single DexScreener pair into the project's normalised :class:`TokenSnapshot`."""
    base = pair.get("baseToken") or {}
    volume = pair.get("volume") or {}
    liquidity = pair.get("liquidity") or {}
    return TokenSnapshot(
        address=address,
        symbol=base.get("symbol"),
        name=base.get("name"),
        market_cap_usd=_to_decimal(pair.get("marketCap") or pair.get("fdv")),
        price_usd=_to_decimal(pair.get("priceUsd")),
        volume_5m_usd=_to_decimal(volume.get("m5")),
        liquidity_usd=_to_decimal(liquidity.get("usd")),
        holder_count=None,
        source="dexscreener",
        fetched_at=datetime.now(UTC),
    )


_RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    aiohttp.ClientError,
    TimeoutError,
)


def _status_label(status_code: int, success: bool) -> str:
    """Map (status_code, success) into the ``SOURCE_CALLS`` ``status`` label."""
    if status_code == 404:
        return "not_found"
    if success:
        return "ok"
    return "unavailable"


class DexScreenerClient:
    """Async client for DexScreener's public token-info API.

    Same posture as :class:`PumpFunClient`: token-bucket rate limit,
    concurrency semaphore, tenacity retry on transient failures, and
    best-effort ``api_call_log`` writes that never break the data path.
    """

    name: str = "dexscreener"

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        sessionmaker: async_sessionmaker[AsyncSession] | None = None,
        log_calls: bool = True,
    ) -> None:
        self._settings = settings if settings is not None else get_settings()
        self._limiter = AsyncLimiter(self._settings.DEXSCREENER_RATE_LIMIT_PER_SEC, time_period=1)
        self._semaphore = asyncio.Semaphore(self._settings.DEXSCREENER_MAX_BATCH_SIZE)
        self._session: aiohttp.ClientSession | None = None
        self._sessionmaker = sessionmaker
        self._log_calls = log_calls and sessionmaker is not None

    async def __aenter__(self) -> Self:
        await self._ensure_session()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self._settings.DEXSCREENER_TIMEOUT_SECONDS)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers={"User-Agent": self._settings.DEXSCREENER_USER_AGENT},
            )
        return self._session

    async def close(self) -> None:
        """Close the underlying aiohttp session. Idempotent."""
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    async def fetch_one(self, address: str) -> TokenSnapshot | None:
        """Fetch a single token's best Solana pair from DexScreener.

        Returns ``None`` if the token is not indexed on Solana. Raises
        :class:`DexScreenerUnavailableError` after retry exhaustion.
        """
        started = time.perf_counter()
        status_code = 0
        error: str | None = None
        success = False
        try:
            payload = await self._get_with_retries([address])
            pair = _select_pair(payload.get("pairs"), address)
            status_code = 200 if pair is not None else 404
            success = True
            return _parse_pair(address, pair) if pair is not None else None
        except DexScreenerUnavailableError as exc:
            error = str(exc)
            raise
        finally:
            if self._log_calls:
                latency_ms = int((time.perf_counter() - started) * 1000)
                try:
                    await self._log_call(
                        endpoint=f"/latest/dex/tokens/{_redact(address)}",
                        status_code=status_code,
                        latency_ms=latency_ms,
                        success=success,
                        error=error,
                    )
                except Exception as log_exc:
                    # The data path must never be broken by the observability path.
                    _log.warning("dexscreener.log_call.outer_failed", error=str(log_exc))
            try:
                SOURCE_CALLS.labels(
                    source=self.name,
                    status=_status_label(status_code, success),
                ).inc()
            except Exception as metric_exc:
                _log.warning("dexscreener.metric.failed", error=str(metric_exc))

    async def fetch_batch(self, addresses: list[str]) -> dict[str, TokenSnapshot]:
        """Fetch multiple tokens in chunks of ``DEXSCREENER_MAX_BATCH_SIZE``.

        DexScreener's ``/latest/dex/tokens/{a,b,c,...}`` endpoint accepts a
        comma-separated address list and returns a single ``pairs`` array
        spanning every requested token. Ordering of pairs in the response
        is not guaranteed; we resolve back to addresses by ``baseToken.address``.
        """
        out: dict[str, TokenSnapshot] = {}
        chunk_size = max(1, self._settings.DEXSCREENER_MAX_BATCH_SIZE)
        chunks = [addresses[i : i + chunk_size] for i in range(0, len(addresses), chunk_size)]
        for chunk in chunks:
            try:
                payload = await self._get_with_retries(chunk)
            except DexScreenerUnavailableError as exc:
                _log.warning("dexscreener.fetch_batch.chunk_failed", error=str(exc))
                continue
            for address in chunk:
                pair = _select_pair(payload.get("pairs"), address)
                if pair is not None:
                    out[address] = _parse_pair(address, pair)
        return out

    async def _get_with_retries(self, addresses: list[str]) -> dict[str, Any]:
        joined = ",".join(addresses)
        log = _log.bind(addresses=[_redact(a) for a in addresses])
        retrying = AsyncRetrying(
            retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
            wait=wait_exponential_jitter(initial=1, max=30),
            stop=stop_after_attempt(self._settings.DEXSCREENER_MAX_RETRY_ATTEMPTS),
            reraise=False,
        )
        try:
            async for attempt in retrying:
                with attempt:
                    return await self._get_inner(joined, log)
        except Exception as exc:
            log.warning("dexscreener.fetch.exhausted", error=str(exc))
            raise DexScreenerUnavailableError(
                f"dexscreener unavailable for {len(addresses)} address(es)"
            ) from exc
        return {}  # unreachable — AsyncRetrying always yields at least once

    async def _get_inner(self, joined_addresses: str, log: Any) -> dict[str, Any]:
        session = await self._ensure_session()
        url = f"{self._settings.DEXSCREENER_BASE_URL}/latest/dex/tokens/{joined_addresses}"
        async with self._limiter, self._semaphore:
            log.debug("dexscreener.fetch", url=url)
            async with session.get(url) as resp:
                if resp.status == 404:
                    return {"pairs": []}
                if 500 <= resp.status < 600:
                    raise aiohttp.ClientResponseError(
                        request_info=resp.request_info,
                        history=resp.history,
                        status=resp.status,
                        message=f"dexscreener {resp.status}",
                    )
                resp.raise_for_status()
                payload = await resp.json()
                if not isinstance(payload, dict):
                    return {"pairs": []}
                return payload

    async def _log_call(
        self,
        *,
        endpoint: str,
        status_code: int,
        latency_ms: int,
        success: bool,
        error: str | None,
    ) -> None:
        """Best-effort write to ``api_call_log``. A failure here is warned, not raised."""
        assert self._sessionmaker is not None  # narrowed by self._log_calls
        try:
            async with self._sessionmaker() as session, session.begin():
                await ApiCallLogRepository(session).record(
                    source=self.name,
                    endpoint=endpoint,
                    status_code=status_code,
                    latency_ms=latency_ms,
                    success=success,
                    error=error,
                )
        except Exception as exc:
            _log.warning("dexscreener.log_call.failed", error=str(exc))
