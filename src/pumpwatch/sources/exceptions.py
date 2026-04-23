"""Domain exceptions for price data sources."""


class PumpFunError(Exception):
    """Base class for every Pump.fun client failure."""


class PumpFunUnavailableError(PumpFunError):
    """Raised after retry attempts are exhausted.

    The underlying aiohttp / timeout error is attached as ``__cause__``.
    Callers should treat this as "the upstream is down right now" and push
    affected jobs to a dead-letter queue rather than crashing.
    """
