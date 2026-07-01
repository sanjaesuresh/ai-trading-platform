"""Event-overlay strategy tests (Phase 5 M6). DB-free, network-free, no LLM."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.backtesting.engine import run_backtest
from app.data.feature_engineering import add_technical_indicators
from app.ml.news_features import build_news_features
from app.strategies.base_strategy import Position, StrategySignal
from app.strategies.event_overlay import EventOverlayParams, EventOverlayStrategy
from app.strategies.registry import StrategyParamError, available_strategies, resolve_strategy
from app.strategies.trend_following import TrendFollowingStrategy


def _bull_row(**overrides) -> pd.Series:
    # A row the trend-following default reads as a BUY.
    row = {
        "timestamp": pd.Timestamp("2023-06-01"),
        "close": 110.0,
        "volume": 1_200.0,
        "sma_20": 105.0,
        "sma_50": 100.0,
        "rsi_14": 55.0,
        "macd": 1.0,
        "macd_signal": 0.5,
        "volume_ma_20": 1_000.0,
        "n_event_flag": 0.0,
        "n_sent_decay": 0.0,
    }
    row.update(overrides)
    return pd.Series(row)


def test_passthrough_when_no_event() -> None:
    overlay = EventOverlayStrategy()
    base = TrendFollowingStrategy()
    row = _bull_row()
    assert overlay.generate_signal(row, Position()).action is base.generate_signal(
        row, Position()
    ).action


def test_passthrough_when_event_columns_absent() -> None:
    overlay = EventOverlayStrategy()
    row = _bull_row()
    row = row.drop(labels=["n_event_flag", "n_sent_decay"])
    # Missing columns → underlying decision unchanged (no crash).
    assert overlay.generate_signal(row, Position()).action in {
        StrategySignal.BUY,
        StrategySignal.HOLD,
    }


def test_adverse_event_vetoes_entry() -> None:
    overlay = EventOverlayStrategy(veto_threshold=0.3)
    row = _bull_row(n_event_flag=1.0, n_sent_decay=-0.8)  # strong adverse event
    decision = overlay.generate_signal(row, Position())
    assert decision.action is StrategySignal.HOLD
    assert "vetoed" in decision.reason


def test_adverse_event_exits_open_position() -> None:
    overlay = EventOverlayStrategy(exit_on_adverse=True)
    row = _bull_row(n_event_flag=1.0, n_sent_decay=-0.8)
    decision = overlay.generate_signal(row, Position(quantity=10.0, entry_price=100.0))
    assert decision.action is StrategySignal.SELL
    assert "exiting" in decision.reason


def test_favourable_event_passes_through() -> None:
    overlay = EventOverlayStrategy()
    row = _bull_row(n_event_flag=1.0, n_sent_decay=0.8)  # positive event
    assert overlay.generate_signal(row, Position()).action is StrategySignal.BUY


def test_below_threshold_event_not_vetoed() -> None:
    overlay = EventOverlayStrategy(veto_threshold=0.5)
    row = _bull_row(n_event_flag=1.0, n_sent_decay=-0.2)  # mild, below threshold
    assert overlay.generate_signal(row, Position()).action is StrategySignal.BUY


# --- params / registry ---


def test_registered() -> None:
    assert "event_overlay" in available_strategies()
    strat = resolve_strategy("event_overlay", {"veto_threshold": 0.4})
    assert isinstance(strat, EventOverlayStrategy)


def test_recursive_overlay_rejected() -> None:
    with pytest.raises(StrategyParamError, match="recursion"):
        resolve_strategy("event_overlay", {"underlying_strategy": "event_overlay"})


def test_extra_params_forbidden() -> None:
    with pytest.raises(StrategyParamError):
        resolve_strategy("event_overlay", {"nope": 1})


def test_underlying_params_flow_through() -> None:
    strat = resolve_strategy(
        "event_overlay",
        {"underlying_strategy": "mean_reversion", "underlying_params": {"entry_std": 1.5}},
    )
    assert strat.underlying_strategy == "mean_reversion"


def test_default_params_shape() -> None:
    p = EventOverlayParams()
    assert p.underlying_strategy == "trend_following"
    assert p.event_flag_col == "n_event_flag"


# --- engine integration: overlay changes trades vs the underlying, net of cost ---


def _news_frame(rows: int, event_bars: list[int], seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0, 1, rows))
    close = np.maximum(close, 5.0)
    raw = pd.DataFrame(
        {
            "timestamp": pd.date_range("2020-01-02", periods=rows, freq="B"),
            "open": close * 0.999,
            "high": close + 1.5,
            "low": close - 1.5,
            "close": close,
            "volume": rng.integers(1_000, 5_000, rows).astype(float),
        }
    )
    frame = add_technical_indicators(raw)
    ts = pd.to_datetime(frame["timestamp"]).dt.normalize()
    if event_bars:
        closes = (ts.iloc[event_bars] + pd.Timedelta(hours=16)).dt.tz_localize(
            "America/New_York"
        )
        ann = pd.DataFrame(
            {
                "published_at": closes.dt.tz_convert("UTC").map(lambda x: x.isoformat()),
                "first_seen_at": closes.dt.tz_convert("UTC").map(lambda x: x.isoformat()),
                "sentiment": [-0.9] * len(event_bars),  # strong adverse
                "relevance": [0.95] * len(event_bars),
            }
        )
    else:
        ann = None
    return build_news_features(frame, ann, embargo=1, event_window=20)


def test_overlay_matches_underlying_when_no_events() -> None:
    frame = _news_frame(120, event_bars=[], seed=3)
    base = run_backtest(frame, TrendFollowingStrategy(), "X")
    overlay = run_backtest(frame, EventOverlayStrategy(), "X")
    assert len(overlay.trades) == len(base.trades)


def test_overlay_changes_trades_when_adverse_events_present() -> None:
    # Adverse events across a stretch should veto/exit, changing the trade path.
    frame = _news_frame(120, event_bars=list(range(40, 90)), seed=3)
    base = run_backtest(frame, TrendFollowingStrategy(), "X")
    overlay = run_backtest(frame, EventOverlayStrategy(), "X")
    assert len(overlay.trades) != len(base.trades) or overlay.final_equity != base.final_equity
