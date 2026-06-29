"""Opt-in smoke test that hits the real Tiingo API.

Skipped by default and never runs in CI. Enable explicitly with BOTH an API key
and the opt-in flag::

    RUN_TIINGO_SMOKE=1 TIINGO_API_KEY=... pytest app/tests/test_tiingo_smoke.py

It exercises the real urllib client end to end: a short date range for a liquid
symbol must come back passing the data-quality gate with real adjustment fields.
"""

from __future__ import annotations

import os
from datetime import date

import pytest

from app.data.data_quality import check_data_quality
from app.data.providers.tiingo import TiingoProvider

_OPT_IN = os.getenv("RUN_TIINGO_SMOKE") == "1" and bool(os.getenv("TIINGO_API_KEY"))

pytestmark = pytest.mark.skipif(
    not _OPT_IN,
    reason="Real-network Tiingo smoke test; set RUN_TIINGO_SMOKE=1 and TIINGO_API_KEY.",
)


def test_real_tiingo_fetch_passes_quality_gate() -> None:
    provider = TiingoProvider(os.environ["TIINGO_API_KEY"], min_interval_s=1.5)
    frame = provider.fetch_daily("AAPL", date(2023, 1, 3), date(2023, 1, 31))
    assert len(frame) > 0
    report = check_data_quality(frame)
    assert report.passed, f"errors: {report.errors}"
    # Real data carries real adjustment fields (not the offline 1.0 passthrough).
    assert frame["adj_close"].notna().all()
