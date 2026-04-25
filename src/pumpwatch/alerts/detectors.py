"""Pure alert detectors — no I/O, no DB, no Redis.

Two detectors:

* :func:`evaluate_thresholds` — compares the latest market cap against
  the subscription's growth/stoploss thresholds (with a configurable
  warning buffer below each).
* :func:`evaluate_volume_spike` — median + MAD detector over a rolling
  history of ``volume_5m_usd`` values. Robust to fat tails (the reason
  the project chose median+MAD over mean+stddev — see ADR #5).

Both return a list of :class:`AlertCandidate` records. The caller
(``subscriber.py``) is responsible for dedup, suppression, persistence,
and dispatch.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from pumpwatch.db.enums import AlertType


@dataclass(frozen=True, slots=True)
class AlertCandidate:
    """A detector hit. Not yet persisted, not yet deduped, not yet sent."""

    alert_type: AlertType
    market_cap: Decimal | None
    payload: dict[str, Any]


def evaluate_thresholds(
    *,
    current_market_cap: Decimal | None,
    baseline_market_cap: Decimal | None,
    growth_threshold_pct: Decimal,
    stoploss_threshold_pct: Decimal,
    warning_buffer_pct: Decimal,
) -> list[AlertCandidate]:
    """Return any threshold candidates the current price triggers.

    A subscription with ``baseline_market_cap`` unset (or zero) is silently
    skipped — there is no defined zero point to grow or fall from.
    Comparisons are inclusive on the HIT side (matches the priority
    classifier's boundary convention in ``scheduler/priority.py``).

    May return zero, one, or two candidates per call: a sub can be
    simultaneously inside a warning band on one side and on a HIT on the
    other if the thresholds are configured asymmetrically. Dedup TTLs
    keep noise sane downstream.
    """
    if current_market_cap is None or baseline_market_cap is None:
        return []
    if baseline_market_cap == 0:
        return []

    delta_pct = (current_market_cap - baseline_market_cap) / baseline_market_cap * Decimal(100)

    candidates: list[AlertCandidate] = []

    # Growth side: positive delta crossing the +growth threshold.
    if delta_pct >= growth_threshold_pct:
        candidates.append(
            AlertCandidate(
                alert_type=AlertType.GROWTH_HIT,
                market_cap=current_market_cap,
                payload={
                    "baseline_market_cap": str(baseline_market_cap),
                    "current_market_cap": str(current_market_cap),
                    "delta_pct": str(delta_pct),
                    "threshold_pct": str(growth_threshold_pct),
                },
            )
        )
    elif delta_pct >= (growth_threshold_pct - warning_buffer_pct):
        candidates.append(
            AlertCandidate(
                alert_type=AlertType.GROWTH_WARNING,
                market_cap=current_market_cap,
                payload={
                    "baseline_market_cap": str(baseline_market_cap),
                    "current_market_cap": str(current_market_cap),
                    "delta_pct": str(delta_pct),
                    "threshold_pct": str(growth_threshold_pct),
                    "warning_buffer_pct": str(warning_buffer_pct),
                },
            )
        )

    # Stoploss side: negative delta whose magnitude crosses the threshold.
    drop_pct = -delta_pct
    if drop_pct >= stoploss_threshold_pct:
        candidates.append(
            AlertCandidate(
                alert_type=AlertType.STOPLOSS_HIT,
                market_cap=current_market_cap,
                payload={
                    "baseline_market_cap": str(baseline_market_cap),
                    "current_market_cap": str(current_market_cap),
                    "drop_pct": str(drop_pct),
                    "threshold_pct": str(stoploss_threshold_pct),
                },
            )
        )
    elif drop_pct >= (stoploss_threshold_pct - warning_buffer_pct):
        candidates.append(
            AlertCandidate(
                alert_type=AlertType.STOPLOSS_WARNING,
                market_cap=current_market_cap,
                payload={
                    "baseline_market_cap": str(baseline_market_cap),
                    "current_market_cap": str(current_market_cap),
                    "drop_pct": str(drop_pct),
                    "threshold_pct": str(stoploss_threshold_pct),
                    "warning_buffer_pct": str(warning_buffer_pct),
                },
            )
        )

    return candidates


def evaluate_volume_spike(
    *,
    current_volume: Decimal | None,
    history: Sequence[Decimal | None],
    k: Decimal,
    min_samples: int,
    current_market_cap: Decimal | None = None,
) -> AlertCandidate | None:
    """Return a ``VOLUME_SPIKE`` candidate iff the current bar is anomalous.

    ``history`` is the rolling list of recent ``volume_5m_usd`` values
    (newest-first or oldest-first — order is irrelevant to a median).
    ``None`` entries are dropped. If fewer than ``min_samples`` non-null
    historical values remain, or if the MAD is zero (degenerate, e.g.
    every historical bar reports the same volume), the detector skips —
    no fallback. Comparison is inclusive on ``k``.
    """
    if current_volume is None:
        return None

    samples = [float(v) for v in history if v is not None]
    if len(samples) < min_samples:
        return None

    median = statistics.median(samples)
    mad = statistics.median(abs(x - median) for x in samples)
    if mad == 0:
        return None

    score = (float(current_volume) - median) / mad
    if score < float(k):
        return None

    return AlertCandidate(
        alert_type=AlertType.VOLUME_SPIKE,
        market_cap=current_market_cap,
        payload={
            "current_volume_5m_usd": str(current_volume),
            "median_volume_5m_usd": f"{median:.4f}",
            "mad": f"{mad:.4f}",
            "score": f"{score:.4f}",
            "k": str(k),
            "samples": len(samples),
        },
    )
