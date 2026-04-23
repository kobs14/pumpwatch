"""Outbound API call observability repository."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from pumpwatch.db.models import ApiCallLog


class ApiCallLogRepository:
    """Encapsulates all SQL against the ``api_call_log`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        source: str,
        endpoint: str,
        status_code: int | None,
        latency_ms: int | None,
        success: bool,
        error: str | None = None,
    ) -> None:
        """Insert a single call-log row."""
        self._session.add(
            ApiCallLog(
                source=source,
                endpoint=endpoint,
                status_code=status_code,
                latency_ms=latency_ms,
                success=success,
                error=error,
            )
        )
        await self._session.flush()
