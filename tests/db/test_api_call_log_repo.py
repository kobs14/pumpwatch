"""Tests for ApiCallLogRepository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pumpwatch.db.models import ApiCallLog
from pumpwatch.db.repos import ApiCallLogRepository


async def test_record_writes_row(db_session: AsyncSession) -> None:
    repo = ApiCallLogRepository(db_session)
    await repo.record(
        source="pumpfun",
        endpoint="/coins/abc",
        status_code=200,
        latency_ms=87,
        success=True,
    )

    row = (
        await db_session.execute(select(ApiCallLog).where(ApiCallLog.endpoint == "/coins/abc"))
    ).scalar_one()
    assert row.source == "pumpfun"
    assert row.status_code == 200
    assert row.latency_ms == 87
    assert row.success is True
    assert row.error is None


async def test_record_failure_with_error(db_session: AsyncSession) -> None:
    repo = ApiCallLogRepository(db_session)
    await repo.record(
        source="pumpfun",
        endpoint="/coins/bad",
        status_code=503,
        latency_ms=30,
        success=False,
        error="service unavailable",
    )

    row = (
        await db_session.execute(select(ApiCallLog).where(ApiCallLog.endpoint == "/coins/bad"))
    ).scalar_one()
    assert row.success is False
    assert row.error == "service unavailable"
