"""Format validators used by bot command handlers."""

from __future__ import annotations

# Base58 alphabet (Bitcoin-style; excludes 0, O, I, l).
_BASE58_ALPHABET = frozenset("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")


def is_valid_solana_mint(candidate: object) -> bool:
    """Return ``True`` if ``candidate`` looks like a Solana mint address.

    Checks base58 alphabet and length (32..44 characters). This is a format
    check only — existence of the mint on-chain and metadata (symbol, name)
    are hydrated later by the data source layer, not here.
    """
    if not isinstance(candidate, str):
        return False
    if not 32 <= len(candidate) <= 44:
        return False
    return all(ch in _BASE58_ALPHABET for ch in candidate)
