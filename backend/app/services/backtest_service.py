"""Orchestrates one backtest run end to end and persists it.

This is the single place the pipeline is wired together:

  CSV mode:  resolve & safety-check csv_path → load → quality gate → …
  DB mode:   query market_data for symbol → transform → quality gate → …
  (shared)   → indicators → engine → metrics → persist run + trades → return.

The data source is selected by the presence or absence of ``req.csv_path``:
  - ``csv_path`` provided → CSV mode (Phase 1 path, unchanged).
  - ``csv_path`` is None  → DB mode (reads stored, adjusted bars by symbol).
"""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from app.backtesting.engine import BacktestResult, EquityPoint, TradeRecord, run_backtest
from app.backtesting.metrics import Metrics, compute_metrics
from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.data.data_quality import check_data_quality
from app.data.db_loader import orm_rows_to_frame, query_market_data
from app.data.feature_engineering import add_technical_indicators
from app.data.market_data_loader import MarketDataError, load_ohlcv_csv
from app.models_db.backtest_run import BacktestRun
from app.models_db.trade import Trade
from app.schemas.backtest import RunDetail, RunRequest
from app.schemas.metrics import MetricsSchema
from app.schemas.trade import EquityPointSchema, TradeSchema
from app.strategies.registry import (
    StrategyParamError,
    UnknownStrategyError,
    resolve_strategy,
)

log = get_logger(__name__)


class BacktestRequestError(ValueError):
    """A client-correctable problem (bad path, bad CSV, failed data quality)."""

    def __init__(self, message: str, details: list[str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or []


def _resolve_csv_path(csv_path: str, settings: Settings) -> Path:
    """Resolve ``csv_path`` and confirm it stays under the allowed data directory.

    Rejects path traversal and arbitrary-file reads. Relative paths are resolved
    against the repo root (the parent of the allowed data directory).
    """
    allowed = settings.allowed_data_path
    raw = Path(csv_path)
    base = allowed.parent  # repo root, since allowed data dir is <repo>/data
    candidate = raw if raw.is_absolute() else (base / raw)
    resolved = candidate.resolve()

    if not (resolved == allowed or allowed in resolved.parents):
        raise BacktestRequestError(
            f"csv_path must resolve under the allowed data directory ({allowed})."
        )
    if not resolved.is_file():
        raise BacktestRequestError(f"CSV file not found: {csv_path}")
    return resolved


def load_and_feature_frame(
    symbol: str, csv_path: str | None, db: Session
) -> pd.DataFrame:
    """Load the source bars, run the data-quality gate, and add indicators.

    The single load→gate→feature seam, shared by the backtest pipeline and the M5
    evaluation pipelines so the data path (and its path-traversal safety check)
    has one implementation. Source is selected by ``csv_path``: provided → CSV
    mode (resolved under the allowed data dir); ``None`` → DB mode (stored adjusted
    bars for ``symbol``). Raises ``BacktestRequestError`` on any client-correctable
    problem (bad path, bad CSV, no stored bars, failed quality gate).
    """
    settings = get_settings()
    if csv_path is not None:
        path = _resolve_csv_path(csv_path, settings)
        try:
            frame = load_ohlcv_csv(path)
        except MarketDataError as exc:
            raise BacktestRequestError(str(exc)) from exc
    else:
        rows = query_market_data(db, symbol)
        if not rows:
            raise BacktestRequestError(
                f"No market data found in the database for symbol '{symbol}'. "
                "Run ingestion for this symbol first, or provide a csv_path."
            )
        frame = orm_rows_to_frame(rows)

    report = check_data_quality(frame)
    if not report.passed:
        raise BacktestRequestError("Data quality check failed.", report.errors)

    return add_technical_indicators(frame)


def run_backtest_pipeline(req: RunRequest, db: Session) -> BacktestRun:
    """Run the full pipeline and persist the result. Returns the saved run."""
    # --- resolve strategy from the registry (fail fast on bad name/params) ---
    try:
        strategy = resolve_strategy(req.strategy_name, req.strategy_params)
    except (UnknownStrategyError, StrategyParamError) as exc:
        raise BacktestRequestError(str(exc)) from exc

    # --- load → quality gate → indicators (shared seam) → engine → metrics → persist ---
    featured = load_and_feature_frame(req.symbol, req.csv_path, db)
    result = run_backtest(
        featured,
        strategy,
        symbol=req.symbol,
        initial_capital=req.initial_capital,
        fee_bps=req.fee_bps,
        slippage_bps=req.slippage_bps,
        max_position_pct=req.max_position_pct,
        target_vol=req.target_vol,
        vol_lookback=req.vol_lookback,
        stop_loss_pct=req.stop_loss_pct,
        take_profit_pct=req.take_profit_pct,
        max_drawdown_cutoff_pct=req.max_drawdown_cutoff_pct,
    )
    metrics = compute_metrics(result.equity_curve, result.trades, req.initial_capital)

    run = _persist(db, req, result, metrics)
    log.info(
        "Backtest run %s persisted: %s fills, return %.2f%%",
        run.id, len(result.trades), result.total_return_pct,
    )
    return run


def _persist(
    db: Session, req: RunRequest, result: BacktestResult, metrics: Metrics
) -> BacktestRun:
    """Persist the run, its equity curve, and its trades in one transaction."""
    equity_curve_json = [
        {
            "timestamp": p.timestamp.isoformat(),
            "equity": p.equity,
            "cash": p.cash,
            "position_value": p.position_value,
        }
        for p in result.equity_curve
    ]

    run = BacktestRun(
        symbol=result.symbol,
        strategy_name=result.strategy_name,
        status="completed",
        initial_capital=result.initial_capital,
        final_equity=result.final_equity,
        total_return_pct=result.total_return_pct,
        max_drawdown_pct=metrics.max_drawdown_pct,
        sharpe_ratio=metrics.sharpe_ratio,
        sortino_ratio=metrics.sortino_ratio,
        win_rate=metrics.win_rate,
        profit_factor=_finite(metrics.profit_factor),
        num_trades=metrics.num_round_trips,
        config=req.model_dump(),
        equity_curve=equity_curve_json,
    )
    run.trades = [
        Trade(
            symbol=t.symbol,
            side=t.side,
            timestamp=t.timestamp.to_pydatetime(),
            price=t.price,
            quantity=t.quantity,
            gross_value=t.gross_value,
            fee=t.fee,
            slippage=t.slippage,
            cash_after=t.cash_after,
            position_after=t.position_after,
            equity_after=t.equity_after,
            reason=t.reason,
        )
        for t in result.trades
    ]

    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _finite(value: float) -> float:
    """Profit factor can be +inf (winners, no losers); store a large finite value."""
    if not math.isfinite(value):
        return 1.0e9
    return value


def build_run_detail(run: BacktestRun) -> RunDetail:
    """Assemble the full detail response, recomputing metrics from stored data."""
    equity_points = [
        EquityPoint(
            timestamp=pd.Timestamp(p["timestamp"]),
            equity=p["equity"],
            cash=p["cash"],
            position_value=p["position_value"],
        )
        for p in (run.equity_curve or [])
    ]
    trade_records = [
        TradeRecord(
            symbol=t.symbol, side=t.side, timestamp=pd.Timestamp(t.timestamp),
            price=t.price, quantity=t.quantity, gross_value=t.gross_value, fee=t.fee,
            slippage=t.slippage, cash_after=t.cash_after, position_after=t.position_after,
            equity_after=t.equity_after, reason=t.reason,
        )
        for t in run.trades
    ]
    metrics = compute_metrics(equity_points, trade_records, run.initial_capital)

    return RunDetail(
        id=run.id,
        symbol=run.symbol,
        strategy_name=run.strategy_name,
        status=run.status,
        initial_capital=run.initial_capital,
        final_equity=run.final_equity,
        total_return_pct=metrics.total_return_pct,
        max_drawdown_pct=metrics.max_drawdown_pct,
        sharpe_ratio=metrics.sharpe_ratio,
        win_rate=metrics.win_rate,
        num_trades=metrics.num_round_trips,
        created_at=run.created_at,
        config=run.config,
        metrics=MetricsSchema(
            total_return_pct=metrics.total_return_pct,
            annualized_return_pct=metrics.annualized_return_pct,
            max_drawdown_pct=metrics.max_drawdown_pct,
            sharpe_ratio=metrics.sharpe_ratio,
            sortino_ratio=metrics.sortino_ratio,
            win_rate=metrics.win_rate,
            profit_factor=_finite(metrics.profit_factor),
            num_round_trips=metrics.num_round_trips,
            num_fills=metrics.num_fills,
            avg_win=metrics.avg_win,
            avg_loss=metrics.avg_loss,
            avg_holding_days=metrics.avg_holding_days,
            exposure_pct=metrics.exposure_pct,
        ),
        equity_curve=[
            EquityPointSchema(
                timestamp=p.timestamp.to_pydatetime(),
                equity=p.equity, cash=p.cash, position_value=p.position_value,
            )
            for p in equity_points
        ],
        trades=[
            TradeSchema(
                symbol=t.symbol, side=t.side, timestamp=t.timestamp.to_pydatetime(),
                price=t.price, quantity=t.quantity, gross_value=t.gross_value, fee=t.fee,
                slippage=t.slippage, cash_after=t.cash_after, position_after=t.position_after,
                equity_after=t.equity_after, reason=t.reason,
            )
            for t in trade_records
        ],
    )
