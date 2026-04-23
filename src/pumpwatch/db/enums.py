"""Shared string enums for columns backed by CHECK constraints.

These are plain ``StrEnum`` classes (Python 3.12+) so the same values are used
in Python code, in SQL writes (StrEnum is a ``str`` subclass), and in the
CHECK-constraint value lists declared on models.
"""

from enum import StrEnum


class Priority(StrEnum):
    """Subscription polling priority tier."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    PAUSED = "paused"


class SubscriptionStatus(StrEnum):
    """Lifecycle state of a user subscription."""

    ACTIVE = "active"
    STOPPED = "stopped"
    ARCHIVED = "archived"


class AlertType(StrEnum):
    """Category of alert fired by the alert engine."""

    GROWTH_HIT = "growth_hit"
    GROWTH_WARNING = "growth_warning"
    STOPLOSS_HIT = "stoploss_hit"
    STOPLOSS_WARNING = "stoploss_warning"
    VOLUME_SPIKE = "volume_spike"
