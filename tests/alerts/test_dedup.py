"""Dedup-TTL tests with fakeredis."""

from __future__ import annotations

import fakeredis.aioredis
import pytest

from pumpwatch.alerts import dedup
from pumpwatch.cache.redis_client import alert_dedup_key
from pumpwatch.config import get_settings
from pumpwatch.db.enums import AlertType


@pytest.fixture
def fake_redis() -> fakeredis.aioredis.FakeRedis:
    return fakeredis.aioredis.FakeRedis()


async def test_should_skip_returns_false_when_no_key(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    assert (
        await dedup.should_skip(fake_redis, user_id=1, address="a", alert_type=AlertType.GROWTH_HIT)
        is False
    )


async def test_mark_fired_then_should_skip_returns_true(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    await dedup.mark_fired(
        fake_redis,
        user_id=1,
        address="a",
        alert_type=AlertType.GROWTH_HIT,
        ttl_seconds=300,
    )
    assert (
        await dedup.should_skip(fake_redis, user_id=1, address="a", alert_type=AlertType.GROWTH_HIT)
        is True
    )


async def test_dedup_keys_isolated_by_user_token_type(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    await dedup.mark_fired(
        fake_redis,
        user_id=1,
        address="a",
        alert_type=AlertType.GROWTH_HIT,
        ttl_seconds=300,
    )
    # Different user.
    assert (
        await dedup.should_skip(fake_redis, user_id=2, address="a", alert_type=AlertType.GROWTH_HIT)
        is False
    )
    # Different address.
    assert (
        await dedup.should_skip(fake_redis, user_id=1, address="b", alert_type=AlertType.GROWTH_HIT)
        is False
    )
    # Different type.
    assert (
        await dedup.should_skip(
            fake_redis, user_id=1, address="a", alert_type=AlertType.STOPLOSS_HIT
        )
        is False
    )


async def test_mark_fired_sets_ttl(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    await dedup.mark_fired(
        fake_redis,
        user_id=1,
        address="a",
        alert_type=AlertType.GROWTH_HIT,
        ttl_seconds=42,
    )
    ttl = await fake_redis.ttl(alert_dedup_key(1, "a", AlertType.GROWTH_HIT))
    # fakeredis returns seconds; allow some slack from request to assertion.
    assert 0 < ttl <= 42


def test_ttl_for_alert_type_uses_configured_settings() -> None:
    settings = get_settings()
    assert (
        dedup.ttl_for_alert_type(AlertType.GROWTH_HIT, settings) == settings.ALERT_DEDUP_HIT_SECONDS
    )
    assert (
        dedup.ttl_for_alert_type(AlertType.STOPLOSS_HIT, settings)
        == settings.ALERT_DEDUP_HIT_SECONDS
    )
    assert (
        dedup.ttl_for_alert_type(AlertType.GROWTH_WARNING, settings)
        == settings.ALERT_DEDUP_WARNING_SECONDS
    )
    assert (
        dedup.ttl_for_alert_type(AlertType.STOPLOSS_WARNING, settings)
        == settings.ALERT_DEDUP_WARNING_SECONDS
    )
    assert (
        dedup.ttl_for_alert_type(AlertType.VOLUME_SPIKE, settings)
        == settings.ALERT_DEDUP_SPIKE_SECONDS
    )
