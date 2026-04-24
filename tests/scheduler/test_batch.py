"""Pure tests for the batch builder."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from pumpwatch.db.enums import Priority
from pumpwatch.db.models import PriceSnapshot
from pumpwatch.db.repos.subscription import SubscriptionTokenRow
from pumpwatch.scheduler.batch import build_batch

NOW = datetime(2026, 4, 24, 12, 0, tzinfo=UTC)


def _row(
    sub_id: int,
    address: str,
    growth: str = "20",
    stoploss: str = "15",
) -> SubscriptionTokenRow:
    return SubscriptionTokenRow(
        subscription_id=sub_id,
        token_address=address,
        growth_threshold_pct=Decimal(growth),
        stoploss_threshold_pct=Decimal(stoploss),
    )


def _snap(market_cap: str, volume: str = "0") -> PriceSnapshot:
    return PriceSnapshot(
        token_address="x",
        market_cap_usd=Decimal(market_cap),
        volume_5m_usd=Decimal(volume),
    )


def test_empty_input_returns_empty_batch() -> None:
    assert build_batch([], {}, NOW) == []


def test_dedups_two_subs_on_same_token() -> None:
    rows = [_row(1, "tokA"), _row(2, "tokA")]
    items = build_batch(rows, {}, NOW)
    assert len(items) == 1
    assert items[0].token_address == "tokA"
    assert sorted(p[0] for p in items[0].subscription_priorities) == [1, 2]


def test_per_token_tier_is_max_across_subs() -> None:
    # Two subs on tokA: one with a tight stoploss (will be HIGH given the
    # current delta), one with a wide growth target (LOW).
    snaps = {
        "tokA": [
            _snap("100", "10"),  # newest
            _snap("100", "10"),
            _snap("100", "10"),
        ],
    }
    rows = [
        _row(1, "tokA", growth="2", stoploss="2"),  # tight → HIGH
        _row(2, "tokA", growth="500", stoploss="500"),  # loose → LOW
    ]
    items = build_batch(rows, snaps, NOW)
    assert len(items) == 1
    assert items[0].tier is Priority.HIGH
    # Per-sub priorities are still independent: one HIGH, one LOW.
    by_sub = dict(items[0].subscription_priorities)
    assert by_sub[1] is Priority.HIGH
    assert by_sub[2] is Priority.LOW


def test_mixed_tiers_across_multiple_tokens() -> None:
    # tokA has snapshots ~on its (tight) growth threshold → HIGH.
    # tokB has no snapshots → falls to LOW regardless of thresholds.
    snaps = {
        "tokA": [
            _snap("101"),  # newest
            _snap("100"),  # oldest → 1% delta, growth target = 1 → HIGH
        ],
    }
    rows = [
        _row(1, "tokA", growth="1", stoploss="1"),
        _row(2, "tokB", growth="500", stoploss="500"),
    ]
    items = build_batch(rows, snaps, NOW)
    by_addr = {item.token_address: item for item in items}
    assert by_addr["tokA"].tier is Priority.HIGH
    assert by_addr["tokB"].tier is Priority.LOW


def test_no_snapshots_falls_back_to_low_when_thresholds_loose() -> None:
    # No snapshots → distance=inf; loose thresholds → LOW.
    items = build_batch([_row(1, "tokA", growth="50", stoploss="50")], {}, NOW)
    assert items[0].tier is Priority.LOW
