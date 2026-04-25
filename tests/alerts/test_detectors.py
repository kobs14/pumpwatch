"""Pure-detector tests: threshold + median+MAD volume spike."""

from __future__ import annotations

from decimal import Decimal

from pumpwatch.alerts.detectors import (
    evaluate_thresholds,
    evaluate_volume_spike,
)
from pumpwatch.db.enums import AlertType

# --- evaluate_thresholds ----------------------------------------------------


def test_thresholds_skip_when_baseline_none() -> None:
    assert (
        evaluate_thresholds(
            current_market_cap=Decimal("100"),
            baseline_market_cap=None,
            growth_threshold_pct=Decimal("10"),
            stoploss_threshold_pct=Decimal("10"),
            warning_buffer_pct=Decimal("2"),
        )
        == []
    )


def test_thresholds_skip_when_baseline_zero() -> None:
    assert (
        evaluate_thresholds(
            current_market_cap=Decimal("100"),
            baseline_market_cap=Decimal("0"),
            growth_threshold_pct=Decimal("10"),
            stoploss_threshold_pct=Decimal("10"),
            warning_buffer_pct=Decimal("2"),
        )
        == []
    )


def test_thresholds_skip_when_current_none() -> None:
    assert (
        evaluate_thresholds(
            current_market_cap=None,
            baseline_market_cap=Decimal("100"),
            growth_threshold_pct=Decimal("10"),
            stoploss_threshold_pct=Decimal("10"),
            warning_buffer_pct=Decimal("2"),
        )
        == []
    )


def test_thresholds_growth_hit_inclusive_on_threshold() -> None:
    # current 110, baseline 100 → +10.00% — exactly on threshold fires.
    candidates = evaluate_thresholds(
        current_market_cap=Decimal("110"),
        baseline_market_cap=Decimal("100"),
        growth_threshold_pct=Decimal("10"),
        stoploss_threshold_pct=Decimal("10"),
        warning_buffer_pct=Decimal("2"),
    )
    assert [c.alert_type for c in candidates] == [AlertType.GROWTH_HIT]


def test_thresholds_growth_warning_band() -> None:
    # +9% with 10% threshold and 2pp buffer → in warning band [8%, 10%).
    candidates = evaluate_thresholds(
        current_market_cap=Decimal("109"),
        baseline_market_cap=Decimal("100"),
        growth_threshold_pct=Decimal("10"),
        stoploss_threshold_pct=Decimal("10"),
        warning_buffer_pct=Decimal("2"),
    )
    assert [c.alert_type for c in candidates] == [AlertType.GROWTH_WARNING]


def test_thresholds_growth_below_warning_no_fire() -> None:
    # +5% with 10% threshold and 2pp buffer → below warning band.
    candidates = evaluate_thresholds(
        current_market_cap=Decimal("105"),
        baseline_market_cap=Decimal("100"),
        growth_threshold_pct=Decimal("10"),
        stoploss_threshold_pct=Decimal("10"),
        warning_buffer_pct=Decimal("2"),
    )
    assert candidates == []


def test_thresholds_stoploss_hit_inclusive() -> None:
    # 90 vs 100 baseline → -10% drop, exactly on stoploss threshold.
    candidates = evaluate_thresholds(
        current_market_cap=Decimal("90"),
        baseline_market_cap=Decimal("100"),
        growth_threshold_pct=Decimal("10"),
        stoploss_threshold_pct=Decimal("10"),
        warning_buffer_pct=Decimal("2"),
    )
    assert [c.alert_type for c in candidates] == [AlertType.STOPLOSS_HIT]


def test_thresholds_stoploss_warning_band() -> None:
    # 91 vs 100 → -9% drop, threshold 10, buffer 2 → in [-10%, -8%).
    candidates = evaluate_thresholds(
        current_market_cap=Decimal("91"),
        baseline_market_cap=Decimal("100"),
        growth_threshold_pct=Decimal("10"),
        stoploss_threshold_pct=Decimal("10"),
        warning_buffer_pct=Decimal("2"),
    )
    assert [c.alert_type for c in candidates] == [AlertType.STOPLOSS_WARNING]


def test_thresholds_carries_market_cap_and_payload() -> None:
    candidates = evaluate_thresholds(
        current_market_cap=Decimal("120"),
        baseline_market_cap=Decimal("100"),
        growth_threshold_pct=Decimal("10"),
        stoploss_threshold_pct=Decimal("10"),
        warning_buffer_pct=Decimal("2"),
    )
    assert len(candidates) == 1
    c = candidates[0]
    assert c.alert_type is AlertType.GROWTH_HIT
    assert c.market_cap == Decimal("120")
    assert c.payload["baseline_market_cap"] == "100"
    assert c.payload["current_market_cap"] == "120"
    assert c.payload["threshold_pct"] == "10"


# --- evaluate_volume_spike --------------------------------------------------


def _hist(*values: float) -> list[Decimal | None]:
    return [Decimal(str(v)) for v in values]


def test_spike_skip_when_current_none() -> None:
    assert (
        evaluate_volume_spike(
            current_volume=None,
            history=_hist(*[100.0] * 12),
            k=Decimal("3"),
            min_samples=12,
        )
        is None
    )


def test_spike_skip_when_below_min_samples() -> None:
    # 11 samples, min 12 → skip even if anomalously high.
    assert (
        evaluate_volume_spike(
            current_volume=Decimal("10000"),
            history=_hist(*[100.0] * 11),
            k=Decimal("3"),
            min_samples=12,
        )
        is None
    )


def test_spike_skip_when_mad_zero_degenerate() -> None:
    # Every sample identical → MAD=0 → degenerate → skip.
    assert (
        evaluate_volume_spike(
            current_volume=Decimal("10000"),
            history=_hist(*[100.0] * 20),
            k=Decimal("3"),
            min_samples=12,
        )
        is None
    )


def test_spike_fires_when_score_at_or_above_k() -> None:
    # 12 alternating values 90/110 → median 100, MAD 10. Current 130 → score 3.0.
    history = _hist(*([90.0, 110.0] * 6))
    candidate = evaluate_volume_spike(
        current_volume=Decimal("130"),
        history=history,
        k=Decimal("3"),
        min_samples=12,
    )
    assert candidate is not None
    assert candidate.alert_type is AlertType.VOLUME_SPIKE
    assert candidate.payload["samples"] == 12
    # score should be ~3.0 (inclusive on k).
    assert float(candidate.payload["score"]) >= 3.0


def test_spike_does_not_fire_below_k() -> None:
    history = _hist(*([90.0, 110.0] * 6))
    assert (
        evaluate_volume_spike(
            current_volume=Decimal("125"),
            history=history,
            k=Decimal("3"),
            min_samples=12,
        )
        is None
    )


def test_spike_drops_none_entries_from_history() -> None:
    history: list[Decimal | None] = [None, None, *(_hist(*([90.0, 110.0] * 6)))]
    candidate = evaluate_volume_spike(
        current_volume=Decimal("130"),
        history=history,
        k=Decimal("3"),
        min_samples=12,
    )
    assert candidate is not None
    assert candidate.payload["samples"] == 12


def test_spike_carries_current_market_cap() -> None:
    history = _hist(*([90.0, 110.0] * 6))
    candidate = evaluate_volume_spike(
        current_volume=Decimal("130"),
        history=history,
        k=Decimal("3"),
        min_samples=12,
        current_market_cap=Decimal("4321"),
    )
    assert candidate is not None
    assert candidate.market_cap == Decimal("4321")
