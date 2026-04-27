"""Pump.fun frontend-API client.

The Pump.fun API is **unofficial**. Endpoints and response shapes are
reverse-engineered from the community and have changed in the past. All
knowledge of the upstream shape is isolated in :func:`_parse_snapshot` so a
breaking change is a one-function fix.
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
from pumpwatch.sources.exceptions import PumpFunUnavailableError

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


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_snapshot(address: str, payload: dict[str, Any]) -> TokenSnapshot:
    """Map a Pump.fun coin payload into a :class:`TokenSnapshot`.

    Keys we try, in order of preference — all are permissive gets so missing
    fields become ``None`` rather than raising:

    - ``market_cap_usd`` ← ``usd_market_cap`` or ``market_cap``
    - ``price_usd``      ← ``price_usd`` (if the upstream ever returns it)
    - ``volume_5m_usd``  ← ``volume_5m`` or ``volume``
    - ``liquidity_usd``  ← ``liquidity_usd`` or ``virtual_sol_reserves_usd``
    - ``holder_count``   ← ``holder_count``
    """
    return TokenSnapshot(
        address=address,
        symbol=payload.get("symbol"),
        name=payload.get("name"),
        market_cap_usd=_to_decimal(payload.get("usd_market_cap") or payload.get("market_cap")),
        price_usd=_to_decimal(payload.get("price_usd")),
        volume_5m_usd=_to_decimal(payload.get("volume_5m") or payload.get("volume")),
        liquidity_usd=_to_decimal(
            payload.get("liquidity_usd") or payload.get("virtual_sol_reserves_usd")
        ),
        holder_count=_to_int(payload.get("holder_count")),
        source="pumpfun",
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


class PumpFunClient:
    """Async client for the Pump.fun frontend API.

    Enforces a token-bucket rate limit and a per-call concurrency semaphore,
    retries transient failures with exponential jitter, and converts
    exhausted retries into :class:`PumpFunUnavailableError`.
    """

    name: str = "pumpfun"

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        sessionmaker: async_sessionmaker[AsyncSession] | None = None,
        log_calls: bool = True,
    ) -> None:
        self._settings = settings if settings is not None else get_settings()
        self._limiter = AsyncLimiter(self._settings.PUMPFUN_RATE_LIMIT_PER_SEC, time_period=1)
        self._semaphore = asyncio.Semaphore(self._settings.PUMPFUN_MAX_BATCH_SIZE)
        self._session: aiohttp.ClientSession | None = None
        # Logging is opt-in: a sessionmaker must be supplied AND log_calls
        # must be true. Without a sessionmaker the client is fully isolated
        # from the DB (the path Session 2's tests exercise).
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
            timeout = aiohttp.ClientTimeout(total=self._settings.PUMPFUN_TIMEOUT_SECONDS)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers={"User-Agent": self._settings.PUMPFUN_USER_AGENT},
            )
        return self._session

    async def close(self) -> None:
        """Close the underlying aiohttp session. Idempotent."""
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    async def fetch_one(self, address: str) -> TokenSnapshot | None:
        """Fetch one coin from Pump.fun.

        Returns ``None`` if the coin is unknown upstream (404 or missing
        payload). Raises :class:`PumpFunUnavailableError` after retry
        attempts are exhausted on transient failures. Writes one summary
        row to ``api_call_log`` per logical call (not per HTTP retry) when
        a sessionmaker was passed to ``__init__``.
        """
        started = time.perf_counter()
        status_code: int = 0  # 0 = transport-level failure (no HTTP response)
        error: str | None = None
        success = False
        try:
            snap = await self._fetch_one_with_retries(address)
            status_code = 200 if snap is not None else 404
            success = True
            return snap
        except PumpFunUnavailableError as exc:
            error = str(exc)
            raise
        finally:
            if self._log_calls:
                latency_ms = int((time.perf_counter() - started) * 1000)
                try:
                    await self._log_call(
                        endpoint=f"/coins/{_redact(address)}",
                        status_code=status_code,
                        latency_ms=latency_ms,
                        success=success,
                        error=error,
                    )
                except Exception as log_exc:
                    # The data path must never be broken by the observability
                    # path. A logging bug is a warning, not a caller-visible
                    # exception.
                    _log.warning("pumpfun.log_call.outer_failed", error=str(log_exc))
            try:
                SOURCE_CALLS.labels(
                    source=self.name,
                    status=_status_label(status_code, success),
                ).inc()
            except Exception as metric_exc:
                _log.warning("pumpfun.metric.failed", error=str(metric_exc))

    async def _fetch_one_with_retries(self, address: str) -> TokenSnapshot | None:
        log = _log.bind(address=_redact(address))
        retrying = AsyncRetrying(
            retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
            wait=wait_exponential_jitter(initial=1, max=30),
            stop=stop_after_attempt(self._settings.PUMPFUN_MAX_RETRY_ATTEMPTS),
            reraise=False,
        )
        try:
            async for attempt in retrying:
                with attempt:
                    return await self._fetch_one_inner(address, log)
        except Exception as exc:  # tenacity re-raises the wrapped error
            log.warning("pumpfun.fetch_one.exhausted", error=str(exc))
            raise PumpFunUnavailableError(f"pumpfun unavailable for {_redact(address)}") from exc
        return None  # unreachable — AsyncRetrying always yields at least once

    async def _log_call(
        self,
        *,
        endpoint: str,
        status_code: int,
        latency_ms: int,
        success: bool,
        error: str | None,
    ) -> None:
        """Best-effort write to ``api_call_log``. A failure here is warned, not raised.

        The data path must not depend on the observability path: if the DB
        is unreachable we still want callers to receive whatever the API
        returned (or the original API error).
        """
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
            _log.warning("pumpfun.log_call.failed", error=str(exc))

    async def _fetch_one_inner(
        self,
        address: str,
        log: Any,
    ) -> TokenSnapshot | None:
        session = await self._ensure_session()
        url = f"{self._settings.PUMPFUN_BASE_URL}/coins/{address}"
        async with self._limiter, self._semaphore:
            log.debug("pumpfun.fetch_one", url=url)
            async with session.get(url) as resp:
                if resp.status == 404:
                    return None
                if 500 <= resp.status < 600:
                    # Raise so tenacity retries.
                    raise aiohttp.ClientResponseError(
                        request_info=resp.request_info,
                        history=resp.history,
                        status=resp.status,
                        message=f"pumpfun {resp.status}",
                    )
                resp.raise_for_status()
                payload = await resp.json()
                if not isinstance(payload, dict):
                    return None
                return _parse_snapshot(address, payload)

    async def fetch_batch(self, addresses: list[str]) -> dict[str, TokenSnapshot]:
        """Fan-out concurrent ``fetch_one`` calls; return a dict of successes."""
        results = await asyncio.gather(
            *(self.fetch_one(a) for a in addresses),
            return_exceptions=True,
        )
        out: dict[str, TokenSnapshot] = {}
        for address, result in zip(addresses, results, strict=True):
            if isinstance(result, TokenSnapshot):
                out[address] = result
            elif isinstance(result, BaseException):
                _log.warning(
                    "pumpfun.fetch_batch.entry_failed",
                    address=_redact(address),
                    error=str(result),
                )
        return out
