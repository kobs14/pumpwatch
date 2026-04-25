"""Suppression rules — mute, paused, quiet hours, DST + wrap-around."""

from __future__ import annotations

from datetime import UTC, datetime, time

from pumpwatch.alerts.suppression import is_suppressed
from pumpwatch.db.enums import Priority, SubscriptionStatus
from pumpwatch.db.models import Subscription, User


def _user(
    *,
    alerts_muted: bool = False,
    quiet_start: time | None = None,
    quiet_end: time | None = None,
    timezone: str | None = "UTC",
) -> User:
    u = User(
        telegram_id=1,
        chat_id=1,
        telegram_username="t",
        alerts_muted=alerts_muted,
        quiet_hours_start=quiet_start,
        quiet_hours_end=quiet_end,
        timezone=timezone,
    )
    return u


def _sub(*, priority: Priority = Priority.HIGH) -> Subscription:
    return Subscription(
        user_id=1,
        token_address="addr",
        growth_threshold_pct=10,
        stoploss_threshold_pct=10,
        priority=priority,
        status=SubscriptionStatus.ACTIVE,
    )


def test_muted_short_circuits() -> None:
    assert (
        is_suppressed(
            _user(alerts_muted=True),
            _sub(),
            datetime(2026, 4, 24, 12, 0, tzinfo=UTC),
        )
        == "muted"
    )


def test_paused_subscription_suppressed() -> None:
    assert (
        is_suppressed(
            _user(),
            _sub(priority=Priority.PAUSED),
            datetime(2026, 4, 24, 12, 0, tzinfo=UTC),
        )
        == "paused"
    )


def test_no_quiet_hours_when_either_endpoint_null() -> None:
    assert (
        is_suppressed(
            _user(quiet_start=time(22, 0), quiet_end=None),
            _sub(),
            datetime(2026, 4, 24, 22, 30, tzinfo=UTC),
        )
        is None
    )
    assert (
        is_suppressed(
            _user(quiet_start=None, quiet_end=time(6, 0)),
            _sub(),
            datetime(2026, 4, 24, 5, 0, tzinfo=UTC),
        )
        is None
    )


def test_start_equal_end_means_24h_muted() -> None:
    assert (
        is_suppressed(
            _user(quiet_start=time(8, 0), quiet_end=time(8, 0)),
            _sub(),
            datetime(2026, 4, 24, 18, 0, tzinfo=UTC),
        )
        == "quiet_hours"
    )


def test_quiet_hours_simple_window_inclusive_start_exclusive_end() -> None:
    user = _user(quiet_start=time(22, 0), quiet_end=time(23, 0))
    # Inside.
    assert is_suppressed(user, _sub(), datetime(2026, 4, 24, 22, 30, tzinfo=UTC)) == "quiet_hours"
    # Exactly start → in.
    assert is_suppressed(user, _sub(), datetime(2026, 4, 24, 22, 0, tzinfo=UTC)) == "quiet_hours"
    # Exactly end → out.
    assert is_suppressed(user, _sub(), datetime(2026, 4, 24, 23, 0, tzinfo=UTC)) is None


def test_quiet_hours_wrap_around_23_to_06() -> None:
    user = _user(quiet_start=time(23, 0), quiet_end=time(6, 0))
    # 00:30 UTC → in.
    assert is_suppressed(user, _sub(), datetime(2026, 4, 24, 0, 30, tzinfo=UTC)) == "quiet_hours"
    # 23:30 UTC → in.
    assert is_suppressed(user, _sub(), datetime(2026, 4, 24, 23, 30, tzinfo=UTC)) == "quiet_hours"
    # 12:00 UTC → out.
    assert is_suppressed(user, _sub(), datetime(2026, 4, 24, 12, 0, tzinfo=UTC)) is None


def test_quiet_hours_respect_user_timezone() -> None:
    # 23:00–06:00 in Asia/Tokyo (UTC+9). At 14:30 UTC it's 23:30 in Tokyo → in window.
    user = _user(
        quiet_start=time(23, 0),
        quiet_end=time(6, 0),
        timezone="Asia/Tokyo",
    )
    assert is_suppressed(user, _sub(), datetime(2026, 4, 24, 14, 30, tzinfo=UTC)) == "quiet_hours"
    # 03:30 UTC = 12:30 Tokyo → out.
    assert is_suppressed(user, _sub(), datetime(2026, 4, 24, 3, 30, tzinfo=UTC)) is None


def test_quiet_hours_handle_dst_forward_in_europe_berlin() -> None:
    # Europe/Berlin springs forward 2026-03-29 02:00 local → 03:00 local.
    # Quiet 01:00–04:00 local; check both before and after the jump.
    user = _user(
        quiet_start=time(1, 0),
        quiet_end=time(4, 0),
        timezone="Europe/Berlin",
    )
    # 00:30 UTC = 01:30 CET (before jump) → in.
    assert is_suppressed(user, _sub(), datetime(2026, 3, 29, 0, 30, tzinfo=UTC)) == "quiet_hours"
    # 01:30 UTC = 03:30 CEST (after jump) → in.
    assert is_suppressed(user, _sub(), datetime(2026, 3, 29, 1, 30, tzinfo=UTC)) == "quiet_hours"
    # 03:00 UTC = 05:00 CEST → out.
    assert is_suppressed(user, _sub(), datetime(2026, 3, 29, 3, 0, tzinfo=UTC)) is None


def test_unknown_timezone_falls_back_to_utc() -> None:
    user = _user(
        quiet_start=time(22, 0),
        quiet_end=time(23, 0),
        timezone="Mars/Olympus",  # bogus, falls back to UTC.
    )
    assert is_suppressed(user, _sub(), datetime(2026, 4, 24, 22, 30, tzinfo=UTC)) == "quiet_hours"


def test_null_timezone_treated_as_utc() -> None:
    user = _user(
        quiet_start=time(22, 0),
        quiet_end=time(23, 0),
        timezone=None,
    )
    assert is_suppressed(user, _sub(), datetime(2026, 4, 24, 22, 30, tzinfo=UTC)) == "quiet_hours"


def test_outside_quiet_hours_returns_none() -> None:
    user = _user(quiet_start=time(22, 0), quiet_end=time(23, 0))
    assert is_suppressed(user, _sub(), datetime(2026, 4, 24, 12, 0, tzinfo=UTC)) is None
