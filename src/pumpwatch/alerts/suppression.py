"""Pure suppression rules — no I/O.

Three reasons an alert can be persisted but *not* dispatched to Telegram:

* ``muted`` — ``User.alerts_muted`` is true.
* ``paused`` — ``Subscription.priority == Priority.PAUSED``.
* ``quiet_hours`` — current local time falls inside the user's quiet
  window. Window math:
    * NULL on either ``quiet_hours_start`` or ``quiet_hours_end`` → no
      quiet hours.
    * ``start == end`` → 24h muted.
    * ``start <= end`` → in-window if ``start <= now < end`` (inclusive
      start, exclusive end).
    * ``start > end`` (wrap-around, e.g. 23:00→06:00) → in-window if
      ``now >= start`` OR ``now < end``.
  The ``User.timezone`` column carries an IANA name; an empty/unknown
  value falls back to ``"UTC"`` and is logged.

Suppressed alerts are still persisted by the caller; ``delivered``
stays ``False`` and the dedup TTL key is still set so unmuting does not
trigger a thundering herd of replayed warnings.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pumpwatch.db.enums import Priority
from pumpwatch.db.models import Subscription, User
from pumpwatch.logging import get_logger

SuppressReason = Literal["muted", "paused", "quiet_hours"]

_log = get_logger(__name__)

_UTC = ZoneInfo("UTC")


def _resolve_zone(name: str | None) -> ZoneInfo:
    if not name:
        return _UTC
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        _log.warning("alerts.suppression.unknown_timezone", timezone=name)
        return _UTC


def _within_window(now_local: time, start: time, end: time) -> bool:
    if start == end:
        return True
    if start < end:
        return start <= now_local < end
    # Wrap-around (e.g., 23:00 → 06:00).
    return now_local >= start or now_local < end


def is_suppressed(
    user: User,
    subscription: Subscription,
    now_utc: datetime,
) -> SuppressReason | None:
    """Return the reason the alert should not be dispatched, or ``None``.

    Order of evaluation: ``alerts_muted`` → ``PAUSED`` priority →
    quiet hours. Earlier reasons short-circuit so we don't pay for a
    timezone lookup on a globally-muted user.
    """
    if user.alerts_muted:
        return "muted"

    # ``Subscription.priority`` reads back as a plain ``str`` against the
    # CHECK-constrained ``String(16)`` column (see Session 4 lesson).
    if subscription.priority == Priority.PAUSED.value:
        return "paused"

    start = user.quiet_hours_start
    end = user.quiet_hours_end
    if start is None or end is None:
        return None

    zone = _resolve_zone(user.timezone)
    now_local = now_utc.astimezone(zone).timetz().replace(tzinfo=None)

    if _within_window(now_local, start, end):
        return "quiet_hours"

    return None
