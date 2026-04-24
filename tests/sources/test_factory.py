"""Source factory unit tests.

The factory is thin by design: it reads ``Settings.PRICE_SOURCE`` and
returns the appropriate concrete ``PriceDataSource``. These tests
confirm both wired-in values and the unknown-value defensive raise.
"""

from __future__ import annotations

from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pumpwatch.config import get_settings
from pumpwatch.sources.factory import build_source
from pumpwatch.sources.fake import FakePriceDataSource
from pumpwatch.sources.pumpfun import PumpFunClient


@pytest.fixture
def _sessionmaker(
    db_session: AsyncSession,  # noqa: ARG001 — fixture triggers env setup
) -> async_sessionmaker[AsyncSession]:
    # The factory never calls the sessionmaker during construction; we
    # just need a type-correct value. ``db_session`` as an indirection
    # avoids reaching into test infrastructure directly.
    return cast(async_sessionmaker[AsyncSession], object())


def test_pumpfun_selected_returns_pumpfun_client(
    monkeypatch: pytest.MonkeyPatch,
    _sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "PRICE_SOURCE", "pumpfun")

    source = build_source(_sessionmaker)

    assert isinstance(source, PumpFunClient)
    assert source.name == "pumpfun"


def test_fake_selected_returns_fake_source(
    monkeypatch: pytest.MonkeyPatch,
    _sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "PRICE_SOURCE", "fake")

    source = build_source(_sessionmaker)

    assert isinstance(source, FakePriceDataSource)
    assert source.name == "fake"


def test_unknown_value_raises(
    monkeypatch: pytest.MonkeyPatch,
    _sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    settings = get_settings()
    # Bypass the ``Literal`` at runtime; the defensive raise exists for
    # exactly this class of misconfiguration.
    monkeypatch.setattr(settings, "PRICE_SOURCE", "dexscreener")

    with pytest.raises(ValueError, match="unknown PRICE_SOURCE"):
        build_source(_sessionmaker)
