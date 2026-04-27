"""Celery tasks owned by the alerts service.

Currently a single Beat-driven reconciliation sweep over recently-failed
alert rows. The task wraps :func:`pumpwatch.alerts.reconciler._reconcile_async`
in ``asyncio.run`` per Session 5 lesson: each Celery task body gets its
own event loop and never shares the alerts service's long-running
``get_redis()`` singleton.
"""

from __future__ import annotations

import asyncio

from pumpwatch.alerts.reconciler import _reconcile_async
from pumpwatch.celery_app import celery


@celery.task(  # type: ignore[untyped-decorator]
    name="pumpwatch.alerts.reconcile_failed",
    queue="default",
)
def reconcile_failed_alerts() -> dict[str, int]:
    """Run one reconciliation pass; return counts dict for observability."""
    return asyncio.run(_reconcile_async())
