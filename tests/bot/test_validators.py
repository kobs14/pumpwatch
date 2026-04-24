"""Tests for the Solana mint format validator."""

from __future__ import annotations

import pytest

from pumpwatch.bot.validators import is_valid_solana_mint

# A selection of generated base58 strings in the Solana mint length range.
# These are not live mints — we're testing format only.
_VALID_CANDIDATES = [
    "So11111111111111111111111111111111111111112",  # 43 chars, wrapped SOL-style
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # 44 chars
    "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",  # 44 chars
    "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrst",  # 43 chars, exhaustive alphabet
    "1" * 32,  # minimum length
]


@pytest.mark.parametrize("mint", _VALID_CANDIDATES)
def test_valid_mints_accepted(mint: str) -> None:
    assert is_valid_solana_mint(mint) is True


@pytest.mark.parametrize(
    "candidate",
    [
        "",  # empty
        "short",  # too short
        "A" * 31,  # one below min
        "A" * 45,  # one above max
        "A" * 100,  # way too long
        "0AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",  # contains '0'
        "OAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",  # contains 'O'
        "IAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",  # contains 'I'
        "lAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",  # contains 'l'
        "!" + "A" * 32,  # non-alphanumeric
    ],
)
def test_invalid_mints_rejected(candidate: str) -> None:
    assert is_valid_solana_mint(candidate) is False


@pytest.mark.parametrize("bad", [None, 123, b"AAAA" * 8, ["list"]])
def test_non_string_rejected(bad: object) -> None:
    assert is_valid_solana_mint(bad) is False
