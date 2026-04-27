"""Pick the concrete ``PriceDataSource`` implementation at runtime.

Gated on ``Settings.PRICE_SOURCE``. Callers hand in a session factory
so the chosen client can write to ``api_call_log``; the fake source
ignores it. DexScreener (ADR #14, ADR #20) is selectable via
``PRICE_SOURCE=dexscreener``.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pumpwatch.config import get_settings
from pumpwatch.sources.base import PriceDataSource
from pumpwatch.sources.dexscreener import DexScreenerClient
from pumpwatch.sources.fake import FakePriceDataSource
from pumpwatch.sources.pumpfun import PumpFunClient


def build_source(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> PriceDataSource:
    """Return the ``PriceDataSource`` selected by ``PRICE_SOURCE``.

    - ``pumpfun``     → ``PumpFunClient`` with ``api_call_log`` wiring.
    - ``dexscreener`` → ``DexScreenerClient`` (fallback when Pump.fun is
      Cloudflare-blocked). Same logging posture.
    - ``fake``        → empty in-memory source; a dev-only safeguard.
      Production paths never route through this value, and tests
      monkey-patch ``_build_source`` directly in ``scheduler/tasks.py``
      rather than flipping the setting.
    """
    settings = get_settings()
    if settings.PRICE_SOURCE == "pumpfun":
        return PumpFunClient(
            settings,
            sessionmaker=sessionmaker,
            log_calls=settings.PUMPFUN_LOG_CALLS,
        )
    if settings.PRICE_SOURCE == "dexscreener":
        return DexScreenerClient(
            settings,
            sessionmaker=sessionmaker,
            log_calls=settings.DEXSCREENER_LOG_CALLS,
        )
    if settings.PRICE_SOURCE == "fake":
        return FakePriceDataSource({})
    # Unreachable because ``PRICE_SOURCE`` is a ``Literal`` — kept as a
    # narrow defensive raise for mypy and future string-typed callers.
    raise ValueError(f"unknown PRICE_SOURCE: {settings.PRICE_SOURCE!r}")
