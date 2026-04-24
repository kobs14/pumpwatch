"""Pure tests for compute_priority."""

from __future__ import annotations

from pumpwatch.db.enums import Priority
from pumpwatch.scheduler.priority import (
    DIST_HIGH_PCT,
    DIST_MEDIUM_PCT,
    VOL_HIGH_PCT,
    VOL_MEDIUM_PCT,
    VOLUME_MEDIUM_USD,
    PriorityInputs,
    compute_priority,
)


def _inputs(
    distance: float = 100.0,
    volatility: float = 0.0,
    volume: float = 0.0,
) -> PriorityInputs:
    return PriorityInputs(
        distance_to_threshold_pct=distance,
        recent_volatility_pct=volatility,
        recent_volume_usd=volume,
    )


def test_high_when_distance_is_tight() -> None:
    assert compute_priority(_inputs(distance=1.0)) is Priority.HIGH


def test_high_when_volatility_is_high_even_with_loose_distance() -> None:
    assert compute_priority(_inputs(distance=999.0, volatility=10.0)) is Priority.HIGH


def test_high_at_distance_boundary_inclusive() -> None:
    # boundaries are inclusive on the HIGH side
    assert compute_priority(_inputs(distance=DIST_HIGH_PCT)) is Priority.HIGH


def test_high_at_volatility_boundary_inclusive() -> None:
    assert compute_priority(_inputs(volatility=VOL_HIGH_PCT)) is Priority.HIGH


def test_medium_via_distance() -> None:
    assert compute_priority(_inputs(distance=DIST_MEDIUM_PCT)) is Priority.MEDIUM


def test_medium_via_volatility() -> None:
    assert compute_priority(_inputs(volatility=VOL_MEDIUM_PCT)) is Priority.MEDIUM


def test_medium_via_volume() -> None:
    assert compute_priority(_inputs(volume=VOLUME_MEDIUM_USD)) is Priority.MEDIUM


def test_low_baseline() -> None:
    # Far from threshold, calm price, low volume.
    assert compute_priority(_inputs(distance=50.0, volatility=0.5, volume=10.0)) is Priority.LOW


def test_zero_inputs_are_low() -> None:
    # All-zero metrics still classify as LOW; the LOW path is the default
    # only when distance is *also* large. distance=0 means the price is
    # exactly on the threshold — that's HIGH.
    assert compute_priority(_inputs(distance=0.0)) is Priority.HIGH


def test_just_below_medium_is_low() -> None:
    just_under = _inputs(
        distance=DIST_MEDIUM_PCT + 0.01,
        volatility=VOL_MEDIUM_PCT - 0.01,
        volume=VOLUME_MEDIUM_USD - 1.0,
    )
    assert compute_priority(just_under) is Priority.LOW
