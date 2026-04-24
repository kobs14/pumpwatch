"""Lazy async Redis client + hot-cache / pub-sub helpers.

Single place that knows the ``pw:*`` key namespace and channel names.
No module-level client — we mirror Session 3's ``get_sessionmaker()``
pattern with ``get_redis()`` so imports stay cheap and tests can
substitute a client without triggering a real connection at import time.

Roles on the single Redis instance (see ADR in PROJECT_STATUS.md):
    - Celery broker + result backend (``celery:*`` keys)
    - Hot cache: ``pw:price:<addr>`` → JSON snapshot view
    - Pub-sub: ``pw:price.updated`` → fire-and-forget event stream

The cache and pub-sub helpers are intentionally thin so callers own the
best-effort try/except; a Redis outage must never break the Postgres
write path (Session 4 defensive-outer-try pattern).
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

import redis.asyncio as aioredis

from pumpwatch.config import get_settings
from pumpwatch.db.enums import Priority

CACHE_KEY_PREFIX: Final[str] = "pw:price:"
"""Prefix for hot-cache keys. ``pw:price:<solana-mint-address>``."""

PRICE_UPDATED_CHANNEL: Final[str] = "pw:price.updated"
"""Global pub-sub channel for ``price.updated`` events."""


def cache_key_for(address: str) -> str:
    """Return the canonical hot-cache key for a token address."""
    return f"{CACHE_KEY_PREFIX}{address}"


def ttl_for_tier(tier: Priority) -> int:
    """Map a subscription tier to its hot-cache TTL in seconds.

    PAUSED (if it ever reaches here) uses the LOW TTL — we still write
    the snapshot and the cache; suppression is a dispatch-time concern
    owned by Session 6.
    """
    settings = get_settings()
    if tier is Priority.HIGH:
        return settings.PRICE_CACHE_TTL_HIGH_SECONDS
    if tier is Priority.MEDIUM:
        return settings.PRICE_CACHE_TTL_MEDIUM_SECONDS
    return settings.PRICE_CACHE_TTL_LOW_SECONDS


_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    """Return a lazy-initialised async Redis client.

    Built from ``Settings.REDIS_URL`` on first call. ``decode_responses``
    stays off — we hand JSON bytes straight to ``SET`` / ``PUBLISH`` and
    decode explicitly on reads.
    """
    global _client
    if _client is None:
        _client = aioredis.from_url(str(get_settings().REDIS_URL))
    return _client


async def close_redis() -> None:
    """Idempotent shutdown hook for entry points."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _reset_for_tests() -> None:
    """Drop the cached client so tests can swap ``REDIS_URL`` between cases."""
    global _client
    _client = None


def _default(obj: Any) -> Any:
    """``json.dumps`` default hook for types stdlib doesn't speak natively.

    ``Decimal`` is serialised as string (preserves precision across the
    wire); ``datetime`` as ISO 8601 (caller is expected to pass UTC).
    """
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"cannot serialise {type(obj).__name__}")


def _encode(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, default=_default, separators=(",", ":")).encode("utf-8")


async def set_price_cache(
    client: aioredis.Redis,
    address: str,
    payload: dict[str, Any],
    ttl_seconds: int,
) -> None:
    """Write the latest snapshot view for ``address`` with a ``ttl_seconds`` TTL.

    Raises whatever the underlying redis client raises; callers are
    responsible for best-effort handling.
    """
    await client.set(cache_key_for(address), _encode(payload), ex=ttl_seconds)


async def publish_price_updated(
    client: aioredis.Redis,
    payload: dict[str, Any],
) -> int:
    """Publish a ``price.updated`` event to the global channel.

    Returns the subscriber count the server reports (useful only for
    observability; a zero-subscriber publish is still a success).
    """
    return int(await client.publish(PRICE_UPDATED_CHANNEL, _encode(payload)))
