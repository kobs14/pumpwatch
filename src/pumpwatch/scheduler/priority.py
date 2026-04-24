"""Pure priority-tier classifier used by the scheduler.

This module decides *how often* a token gets polled — not whether anything
weird is happening with it. The volume-spike / median+MAD anomaly detector
that decides whether to fire an alert lives in the alert engine (Session 6).

No Celery, no DB, no I/O. Trivially testable in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass

from pumpwatch.db.enums import Priority

# Tunable thresholds. Surfaced as module-level constants so they're easy to
# find and adjust later without grepping through `if`s.
DIST_HIGH_PCT: float = 2.0
"""Distance to either threshold (pp) at-or-below which a sub is HIGH."""

VOL_HIGH_PCT: float = 8.0
"""Recent volatility (stddev of pct change, pp) at-or-above which a sub is HIGH."""

DIST_MEDIUM_PCT: float = 10.0
"""Distance to either threshold (pp) at-or-below which a sub is MEDIUM."""

VOL_MEDIUM_PCT: float = 3.0
"""Recent volatility (pp) at-or-above which a sub is MEDIUM."""

VOLUME_MEDIUM_USD: float = 50_000.0
"""Recent volume mean (USD) at-or-above which a sub is MEDIUM."""


@dataclass(frozen=True, slots=True)
class PriorityInputs:
    """Per-subscription metrics fed to ``compute_priority``.

    Distance is the smaller of |growth distance| and |stoploss distance| — a
    sub is high-priority if the price is near *either* trigger, since
    both growth-hit and stoploss-hit alerts are equally important.
    """

    distance_to_threshold_pct: float
    recent_volatility_pct: float
    recent_volume_usd: float


def compute_priority(inputs: PriorityInputs) -> Priority:
    """Map metrics to a polling tier.

    Returns ``HIGH``, ``MEDIUM``, or ``LOW``. Never returns ``PAUSED``;
    that tier is reserved for explicit user-mute / quiet-hours logic in
    Session 6.

    Boundary behaviour: comparisons are inclusive (``<=`` / ``>=``) on the
    HIGH/MEDIUM side. A subscription exactly at ``DIST_HIGH_PCT`` is HIGH.
    """
    if (
        inputs.distance_to_threshold_pct <= DIST_HIGH_PCT
        or inputs.recent_volatility_pct >= VOL_HIGH_PCT
    ):
        return Priority.HIGH

    if (
        inputs.distance_to_threshold_pct <= DIST_MEDIUM_PCT
        or inputs.recent_volatility_pct >= VOL_MEDIUM_PCT
        or inputs.recent_volume_usd >= VOLUME_MEDIUM_USD
    ):
        return Priority.MEDIUM

    return Priority.LOW
