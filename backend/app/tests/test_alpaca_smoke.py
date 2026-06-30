"""Opt-in smoke test that hits the real Alpaca **paper** API.

Skipped by default and never runs in CI. Enable explicitly with BOTH the paper
keys and the opt-in flag::

    RUN_ALPACA_SMOKE=1 ALPACA_API_KEY=... ALPACA_SECRET_KEY=... \
        pytest app/tests/test_alpaca_smoke.py

Read-only: it reads the market clock and account snapshot from the real paper
endpoint. It never submits, cancels, or mutates any order — so it is safe to run
against a live paper account at any time.
"""

from __future__ import annotations

import os

import pytest

from app.brokers.alpaca import ALPACA_PAPER_BASE_URL, AlpacaPaperBroker

_OPT_IN = (
    os.getenv("RUN_ALPACA_SMOKE") == "1"
    and bool(os.getenv("ALPACA_API_KEY"))
    and bool(os.getenv("ALPACA_SECRET_KEY"))
)

pytestmark = pytest.mark.skipif(
    not _OPT_IN,
    reason=(
        "Real-network Alpaca paper smoke test; set RUN_ALPACA_SMOKE=1, "
        "ALPACA_API_KEY, and ALPACA_SECRET_KEY."
    ),
)


def test_real_alpaca_paper_read_only() -> None:
    broker = AlpacaPaperBroker(
        os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"]
    )
    # The adapter can only ever talk to the paper host.
    assert broker._base_url == ALPACA_PAPER_BASE_URL

    clock = broker.get_clock()
    assert clock.timestamp is not None

    account = broker.get_account()
    assert account.equity >= 0.0
    assert account.currency == "USD"
