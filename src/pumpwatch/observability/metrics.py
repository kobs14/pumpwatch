"""Prometheus counters/gauges + per-service ``/metrics`` server.

All metric handles live here so any service module can ``from
pumpwatch.observability.metrics import ALERTS_FIRED`` and increment.
The HTTP exporter is started by each long-running service (bot,
scheduler, alerts) and by the Celery worker via the ``worker_init``
signal in :mod:`pumpwatch.celery_app`.

Multiproc mode (Celery worker only) is enabled by setting
``PROMETHEUS_MULTIPROC_DIR`` in that container's environment *before*
Python boots. The Counter/Gauge handles below check the env var on
construction; setting it later has no effect on already-defined
handles. ``start_metrics_server`` notices the same env var and binds
``/metrics`` against a ``MultiProcessCollector``-backed registry that
aggregates across forked pool processes.

The data path must never be broken by the observability path: the
server-start helper logs and swallows binding failures (port in use,
no permission, etc.) so a misconfigured port can't crash a service.
"""

from __future__ import annotations

import os

from prometheus_client import Counter, Gauge

from pumpwatch.logging import get_logger

_log = get_logger(__name__)


# ---- Alerts service counters -----------------------------------------

ALERTS_FIRED = Counter(
    "pumpwatch_alerts_fired_total",
    "Alerts fired by the engine, before suppression / dispatch.",
    ["type"],
)

ALERTS_SUPPRESSED = Counter(
    "pumpwatch_alerts_suppressed_total",
    "Alerts persisted but not dispatched due to mute / quiet hours / paused.",
    ["reason"],
)

ALERTS_DELIVERY_FAILED = Counter(
    "pumpwatch_alerts_delivery_failed_total",
    "Alert dispatches that failed even after the dispatcher's inline retry.",
)

# ---- Source-layer counters (worker) ----------------------------------

SOURCE_CALLS = Counter(
    "pumpwatch_source_calls_total",
    "Calls made to a price-data source, by terminal status.",
    ["source", "status"],
)

# ---- Periodic gauges (refreshed by a Beat task) ----------------------

CELERY_QUEUE_DEPTH = Gauge(
    "pumpwatch_celery_queue_depth",
    "Pending tasks in each Celery queue (by queue name).",
    ["queue"],
    multiprocess_mode="max",
)

DLQ_SIZE = Gauge(
    "pumpwatch_dlq_size",
    "Distinct token addresses currently sitting in dlq_entries.",
    multiprocess_mode="max",
)


# ---- HTTP exporter ----------------------------------------------------

_metrics_started = False


def start_metrics_server(port: int) -> None:
    """Bind a Prometheus ``/metrics`` endpoint on ``port``. Idempotent.

    A failure to bind is warned but does not raise — observability must
    never take down the data path. Repeated calls within the same
    process no-op (the global guard prevents accidental double-bind in
    tests or signal handlers).
    """
    global _metrics_started
    if _metrics_started:
        return
    try:
        multiproc_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
        if multiproc_dir:
            os.makedirs(multiproc_dir, exist_ok=True)
            # Lazy imports — these are only needed in multiproc mode.
            from prometheus_client import (  # noqa: PLC0415
                CollectorRegistry,
                multiprocess,
                start_http_server,
            )

            registry = CollectorRegistry()
            multiprocess.MultiProcessCollector(registry)  # type: ignore[no-untyped-call]
            start_http_server(port, registry=registry)
        else:
            from prometheus_client import start_http_server  # noqa: PLC0415

            start_http_server(port)
        _metrics_started = True
        _log.info(
            "observability.metrics.started",
            port=port,
            multiproc=bool(multiproc_dir),
        )
    except Exception as exc:  # noqa: BLE001 — best-effort; never break data path
        _log.warning("observability.metrics.start_failed", port=port, error=str(exc))
