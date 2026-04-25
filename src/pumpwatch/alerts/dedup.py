"""Redis-TTL dedup for alerts.

Primary cooldown enforcement. Pairs with the DB-side
``AlertRepository.recent_for_subscription`` backstop: if Redis is
unavailable, callers must fall back to the DB read.

Keys are SETEX'd with a per-alert-type TTL on first fire; any second fire
inside the cooldown sees the key present and skips. The TTLs themselves
are owned by ``Settings`` (no magic numbers in detector code).
"""

from __future__ import annotations

import redis.asyncio as aioredis

from pumpwatch.cache.redis_client import alert_dedup_key
from pumpwatch.config import Settings
from pumpwatch.db.enums import AlertType
from pumpwatch.logging import get_logger

_log = get_logger(__name__)


def ttl_for_alert_type(alert_type: AlertType, settings: Settings) -> int:
    """Return the dedup-cooldown TTL (seconds) for a given alert type."""
    if alert_type in (AlertType.GROWTH_HIT, AlertType.STOPLOSS_HIT):
        return settings.ALERT_DEDUP_HIT_SECONDS
    if alert_type in (AlertType.GROWTH_WARNING, AlertType.STOPLOSS_WARNING):
        return settings.ALERT_DEDUP_WARNING_SECONDS
    return settings.ALERT_DEDUP_SPIKE_SECONDS


async def should_skip(
    client: aioredis.Redis,
    user_id: int,
    address: str,
    alert_type: AlertType,
) -> bool:
    """Return ``True`` if the dedup key is set (alert fired within TTL).

    Raises whatever the underlying client raises; callers wrap in their
    own try/except and fall back to the DB-side backstop on Redis
    failure (Session 5 two-layer defensive pattern).
    """
    raw = await client.get(alert_dedup_key(user_id, address, alert_type))
    return raw is not None


async def mark_fired(
    client: aioredis.Redis,
    user_id: int,
    address: str,
    alert_type: AlertType,
    ttl_seconds: int,
) -> None:
    """SETEX the dedup key with ``ttl_seconds`` TTL.

    Best-effort: any failure is the caller's to log and swallow. The
    persisted alert row + DB-side backstop guarantee correctness even
    if this write is silently dropped — at worst the next fire isn't
    deduped and the user sees a duplicate alert.
    """
    await client.set(
        alert_dedup_key(user_id, address, alert_type),
        b"1",
        ex=ttl_seconds,
    )
