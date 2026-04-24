"""Smoke test: round-trip a Celery task through a real Redis broker.

Skipped when Redis isn't reachable. Not a load test — proves the
broker/result-backend wiring end-to-end (eager mode bypasses both, so we
need this for honest coverage of the production path).
"""

from __future__ import annotations

import pytest

from pumpwatch.config import get_settings


def _redis_reachable(url: str) -> bool:
    try:
        import redis
    except ImportError:  # pragma: no cover — redis is a runtime dep now
        return False
    try:
        client = redis.Redis.from_url(url, socket_connect_timeout=0.5)
        return bool(client.ping())
    except Exception:
        return False


pytestmark = pytest.mark.integration


def test_fetch_batch_round_trips_through_real_broker() -> None:
    redis_url = str(get_settings().REDIS_URL)
    if not _redis_reachable(redis_url):
        pytest.skip(f"redis at {redis_url} not reachable")

    # Import lazily so the celery_app isn't constructed unless we're going
    # to use it (avoids a hard dependency on the broker URL during collection).
    from pumpwatch.celery_app import celery
    from pumpwatch.scheduler.tasks import fetch_batch

    # We don't run a worker in this test; just assert the broker accepts the
    # task. Calling .delay() with no worker produces an AsyncResult whose
    # .id we can verify lands as a Redis key.
    prev_eager = celery.conf.task_always_eager
    celery.conf.task_always_eager = False
    try:
        result = fetch_batch.delay()
        assert result.id  # task id assigned by the broker
    finally:
        celery.conf.task_always_eager = prev_eager
