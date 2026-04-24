"""Pure batch builder.

Given the active subscriptions and recent snapshots, produces the list of
unique tokens to poll on the next tick, each annotated with the tier the
dispatch task should route through.

Pure: no DB, no Celery, no I/O. Structurally testable in isolation.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from pumpwatch.db.enums import Priority
from pumpwatch.db.models import PriceSnapshot
from pumpwatch.db.repos.subscription import SubscriptionTokenRow
from pumpwatch.scheduler.priority import PriorityInputs, compute_priority

_TIER_RANK: dict[Priority, int] = {
    Priority.LOW: 0,
    Priority.MEDIUM: 1,
    Priority.HIGH: 2,
    # PAUSED is not produced by the scheduler; if it ever appears here,
    # treat it as the lowest rank so it never wins the per-token max.
    Priority.PAUSED: -1,
}


@dataclass(frozen=True, slots=True)
class BatchItem:
    """One unique token to poll on this tick.

    ``tier`` is the max priority across all subs watching this token —
    drives queue routing of the per-token fetch task.
    ``subscription_priorities`` is the per-sub assignment that gets
    persisted so the bot's `/list` and the alert engine can see the
    current tier per user.
    """

    token_address: str
    tier: Priority
    subscription_priorities: list[tuple[int, Priority]] = field(default_factory=list)


def _to_float(value: Decimal | None) -> float | None:
    """Convert a possibly-missing ``Decimal`` to ``float`` for stats."""
    if value is None:
        return None
    return float(value)


def _current_pct_delta(snapshots: list[PriceSnapshot]) -> float | None:
    """Percentage change between the oldest and newest snapshot's market cap.

    Snapshots are expected newest-first (the repo orders them that way).
    Returns ``None`` if we don't have two data points or the baseline is
    zero / missing.
    """
    if len(snapshots) < 2:
        return None
    newest = _to_float(snapshots[0].market_cap_usd)
    oldest = _to_float(snapshots[-1].market_cap_usd)
    if newest is None or oldest is None or oldest == 0.0:
        return None
    return (newest - oldest) / oldest * 100.0


def _recent_volatility_pct(snapshots: list[PriceSnapshot]) -> float:
    """Sample stddev of consecutive pct changes in market cap. ``0`` if undefined."""
    if len(snapshots) < 3:
        return 0.0
    caps = [_to_float(s.market_cap_usd) for s in snapshots]
    # Need consecutive non-zero pairs to compute pct change.
    changes: list[float] = []
    for prev, curr in zip(caps[1:], caps[:-1], strict=False):
        if prev is None or curr is None or prev == 0.0:
            continue
        changes.append((curr - prev) / prev * 100.0)
    if len(changes) < 2:
        return 0.0
    return float(statistics.stdev(changes))


def _recent_volume_usd(snapshots: list[PriceSnapshot]) -> float:
    """Arithmetic mean of ``volume_5m_usd`` across snapshots, skipping ``None``."""
    vols = [v for s in snapshots if (v := _to_float(s.volume_5m_usd)) is not None]
    if not vols:
        return 0.0
    return sum(vols) / len(vols)


def _distance_to_either_threshold(
    current_delta_pct: float | None,
    growth_threshold_pct: Decimal,
    stoploss_threshold_pct: Decimal,
) -> float:
    """Min absolute distance (in pp) between the current delta and either trigger.

    Growth fires when ``delta >= +growth``; stoploss when ``delta <= -stoploss``.
    No snapshots ⇒ ``inf`` so the sub doesn't get false-promoted to HIGH.
    """
    if current_delta_pct is None:
        return float("inf")
    growth = float(growth_threshold_pct)
    stoploss = float(stoploss_threshold_pct)
    return min(
        abs(growth - current_delta_pct),
        abs(current_delta_pct - (-stoploss)),
    )


def _max_tier(a: Priority, b: Priority) -> Priority:
    return a if _TIER_RANK[a] >= _TIER_RANK[b] else b


def build_batch(
    rows: Iterable[SubscriptionTokenRow],
    snapshots_by_token: Mapping[str, list[PriceSnapshot]],
    now: datetime,  # noqa: ARG001 — reserved for future time-windowed logic
) -> list[BatchItem]:
    """Assemble one ``BatchItem`` per unique token across all subs.

    For each sub: derive ``PriorityInputs`` from its thresholds and the
    token's recent snapshots, classify via ``compute_priority``, then group
    by token. The token's tier is the max across its subs so a single
    high-priority watcher escalates the polling cadence for everyone.
    """
    by_token: dict[str, BatchItem] = {}

    for row in rows:
        snaps = list(snapshots_by_token.get(row.token_address, ()))
        delta = _current_pct_delta(snaps)
        inputs = PriorityInputs(
            distance_to_threshold_pct=_distance_to_either_threshold(
                delta, row.growth_threshold_pct, row.stoploss_threshold_pct
            ),
            recent_volatility_pct=_recent_volatility_pct(snaps),
            recent_volume_usd=_recent_volume_usd(snaps),
        )
        sub_tier = compute_priority(inputs)

        existing = by_token.get(row.token_address)
        if existing is None:
            by_token[row.token_address] = BatchItem(
                token_address=row.token_address,
                tier=sub_tier,
                subscription_priorities=[(row.subscription_id, sub_tier)],
            )
        else:
            existing.subscription_priorities.append((row.subscription_id, sub_tier))
            new_tier = _max_tier(existing.tier, sub_tier)
            if new_tier is not existing.tier:
                # BatchItem is frozen; rebuild with the escalated tier.
                by_token[row.token_address] = BatchItem(
                    token_address=existing.token_address,
                    tier=new_tier,
                    subscription_priorities=existing.subscription_priorities,
                )

    return list(by_token.values())
