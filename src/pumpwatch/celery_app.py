"""Celery application + Beat schedule.

Single source of truth for the Celery instance used by the scheduler
(Beat) and worker processes. Importing this module is safe — it does
not open a Postgres connection. ``get_settings()`` is cached and only
reads env, and the broker URL is just a string passed to Celery.

Signal handlers at the bottom of the module bind per-process Prometheus
``/metrics`` endpoints when Beat or a worker process boots. The worker
process inherits any ``PROMETHEUS_MULTIPROC_DIR`` env var set by the
container, which is what kicks ``prometheus_client`` into multiproc
mode for the prefork pool — the env var must already be present at
Counter-construction time, so it is set on the worker container only.
"""

from __future__ import annotations

from typing import Any

from celery import Celery
from celery.signals import beat_init, worker_init
from kombu import Queue

from pumpwatch.config import get_settings
from pumpwatch.logging import get_logger

_settings = get_settings()
_log = get_logger(__name__)

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
        "reconcile-failed-alerts": {
            "task": "pumpwatch.alerts.reconcile_failed",
            "schedule": float(_settings.ALERT_RECONCILE_INTERVAL_SECONDS),
        },
    },
)

# Worker autodiscovers tasks from these packages on startup.
celery.autodiscover_tasks(["pumpwatch.scheduler", "pumpwatch.alerts", "pumpwatch.observability"])


@worker_init.connect  # type: ignore[untyped-decorator]
def _start_worker_metrics(sender: Any = None, **_kwargs: Any) -> None:
    """Bind the worker's ``/metrics`` port once when the worker boots.

    Runs in the master worker process. Pool children fork from here and
    inherit the multiproc env var. The metrics endpoint aggregates
    across pool processes via ``MultiProcessCollector`` (configured
    inside :func:`pumpwatch.observability.metrics.start_metrics_server`).
    """
    from pumpwatch.observability.metrics import start_metrics_server

    start_metrics_server(_settings.METRICS_PORT_WORKER)


@beat_init.connect  # type: ignore[untyped-decorator]
def _start_beat_metrics(sender: Any = None, **_kwargs: Any) -> None:
    """Bind the scheduler's ``/metrics`` port when Beat boots."""
    from pumpwatch.observability.metrics import start_metrics_server

    start_metrics_server(_settings.METRICS_PORT_SCHEDULER)


# Add the periodic gauge-refresh task to the Beat schedule. Imports
# happen inside the function so module import stays cheap; the Beat
# entry name lives next to the existing entries above for visibility.
celery.conf.beat_schedule["refresh-prometheus-gauges"] = {
    "task": "pumpwatch.observability.refresh_gauges",
    "schedule": float(_settings.METRICS_GAUGE_REFRESH_SECONDS),
}
