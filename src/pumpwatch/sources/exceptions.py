"""Domain exceptions for price data sources."""


class SourceError(Exception):
    """Base class for every price-source client failure."""


class SourceUnavailableError(SourceError):
    """Raised by any source after retry attempts are exhausted.

    The underlying aiohttp / timeout error is attached as ``__cause__``.
    Callers should treat this as "the upstream is down right now" and push
    affected jobs to a dead-letter queue rather than crashing.
    """


class PumpFunError(SourceError):
    """Base class for every Pump.fun client failure."""


class PumpFunUnavailableError(PumpFunError, SourceUnavailableError):
    """Raised when Pump.fun is unavailable after retry exhaustion."""


class DexScreenerError(SourceError):
    """Base class for every DexScreener client failure."""


class DexScreenerUnavailableError(DexScreenerError, SourceUnavailableError):
    """Raised when DexScreener is unavailable after retry exhaustion."""
