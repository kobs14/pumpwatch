"""Celery application + Beat schedule.

Single source of truth for the Celery instance used by the scheduler
(Beat) and worker processes. Importing this module is safe — it does
not open a Postgres connection. ``get_settings()`` is cached and only
reads env, and the broker URL is just a string passed to Celery.
"""

from __future__ import annotations

from celery import Celery
from kombu import Queue

from pumpwatch.config import get_settings

_settings = get_settings()

celery: Celery = Celery(
    "pumpwatch",
    broker=str(_settings.REDIS_URL),
    backend=str(_settings.REDIS_URL),
)

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Short TTL on result backend keys so Redis doesn't accumulate forever.
    result_expires=3600,
    # I/O-bound work: ack after success, fetch one task at a time so a
    # crashed worker requeues exactly the in-flight job.
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_queue="default",
    task_queues=(
        Queue("default"),
        Queue("high"),
        Queue("medium"),
        Queue("low"),
    ),
    beat_schedule={
        "fetch-batch": {
            "task": "pumpwatch.scheduler.fetch_batch",
            "schedule": float(_settings.SCHEDULER_FETCH_INTERVAL_SECONDS),
        },
    },
)

# Tasks live in the scheduler package; autodiscover registers them on
# worker startup. The list intentionally does not include ``workers``
# yet — Session 5 will own that namespace.
celery.autodiscover_tasks(["pumpwatch.scheduler"])
