"""Test helpers for Celery-using tests.

The ``eager_celery`` fixture flips Celery into in-process synchronous mode
so ``task.delay()`` runs the task body immediately and surfaces exceptions.
Useful for exercising task wiring without standing up a real broker.

**Caveat**: eager mode bypasses Kombu routing — ``apply_async(queue=...)``
is a no-op. Tests that need to assert which queue a task would land on
must inspect the ``BatchItem.tier`` value instead.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture
def eager_celery() -> Iterator[None]:
    """Run Celery tasks inline and re-raise their exceptions."""
    from pumpwatch.celery_app import celery

    prev_eager = celery.conf.task_always_eager
    prev_propagate = celery.conf.task_eager_propagates
    celery.conf.task_always_eager = True
    celery.conf.task_eager_propagates = True
    try:
        yield
    finally:
        celery.conf.task_always_eager = prev_eager
        celery.conf.task_eager_propagates = prev_propagate
