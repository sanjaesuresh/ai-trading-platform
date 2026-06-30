"""Paper-trading service: the daily cycle, reconciliation, and persistence (M3).

The single seam the runner and the API both call. One deployment's daily cycle:

    read latest daily bars → portfolio core computes target orders → diff against
    the broker's actual positions → submit via BrokerPort → poll fills →
    reconcile broker truth into platform state → persist snapshots.

Design split for testability: the decision/submit/reconcile logic is pure
functions over a ``BrokerPort`` and in-memory featured frames (driven by the
deterministic ``FakeBroker`` with no DB), and ``run_paper_cycle`` is the thin DB
orchestration that reads bars, calls the pure pieces, and writes the rows.

Execution model (matches the backtest's next-bar-open semantics): the cycle runs
for a ``trading_day``; the decision uses the latest bar strictly *before* that day
(no look-ahead), and the order fills at ``trading_day``'s open via an
opening-auction (OPG) order. The realized fill is compared to the backtest's
modeled open for that day (the implementation-shortfall attribution, §3.2/§11).

Idempotency: client order ids are deterministic per (deployment, day, symbol,
side), so a re-run reconciles rather than double-submits; recorded fills are keyed
by broker fill id; the portfolio snapshot is upserted per (deployment, day).
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.backtesting.metrics import Metrics
from app.backtesting.portfolio_backtest import run_portfolio_backtest
from app.backtesting.portfolio_core import (
    PortfolioConfig,
    PortfolioPosition,
    PortfolioState,
    build_symbol_context,
    evaluate_portfolio,
    portfolio_equity,
)
from app.backtesting.portfolio_metrics import compute_portfolio_metrics
from app.brokers.base import (
    BrokerPort,
    OrderRequest,
    OrderSide,
    OrderStatus,
    TimeInForce,
)
from app.core.logging import get_logger
from app.data.db_loader import orm_rows_to_frame, query_market_data
from app.data.feature_engineering import add_technical_indicators
from app.models_db.paper_trading import (
    PaperDeployment,
    PaperFill,
    PaperOrder,
    PaperPositionSnapshot,
    PortfolioSnapshot,
    ReconciliationLog,
    SystemFlag,
)
from app.strategies.base_strategy import Position
from app.strategies.registry import resolve_strategy

log = get_logger(__name__)

_GLOBAL_KILL_FLAG = "global_kill"

# PortfolioConfig knobs allowed in the deployment ``config`` blob.
_CONFIG_FIELDS = {
    "fee_bps",
    "slippage_bps",
    "target_vol",
    "vol_lookback",
    "max_position_pct",
    "gross_exposure_cap",
    "max_open_positions",
    "per_order_notional_cap",
    "stop_loss_pct",
    "take_profit_pct",
    "max_drawdown_cutoff_pct",
}


# --- Plain spec + result types (no ORM, no DB) ------------------------------


@dataclass(frozen=True)
class DeploymentSpec:
    deployment_id: int
    strategy_name: str
    params: dict
    symbols: list[str]
    config: PortfolioConfig


@dataclass
class PlannedOrder:
    request: OrderRequest
    symbol: str
    side: str
    quantity: float
    notional: float
    reference_price: float
    reason: str
    client_order_id: str


@dataclass
class CyclePlan:
    orders: list[PlannedOrder] = field(default_factory=list)
    halt_triggered: bool = False
    halt_reason: str = ""
    decision_marks: dict[str, float] = field(default_factory=dict)
    peak_equity: float = 0.0


@dataclass
class FillRecord:
    client_order_id: str
    broker_fill_id: str | None
    symbol: str
    side: str
    quantity: float
    price: float
    modeled_reference_price: float
    slippage_delta: float
    filled_at: datetime | None


@dataclass
class ReconRecord:
    kind: str
    symbol: str | None
    detail: str


# --- Config + spec helpers --------------------------------------------------


def build_portfolio_config(starting_capital: float, config: dict) -> PortfolioConfig:
    """Build a ``PortfolioConfig`` from a deployment's stored config blob."""
    known = {k: v for k, v in (config or {}).items() if k in _CONFIG_FIELDS}
    return PortfolioConfig(initial_capital=float(starting_capital), **known)


def spec_from_deployment(deployment: PaperDeployment) -> DeploymentSpec:
    return DeploymentSpec(
        deployment_id=deployment.id,
        strategy_name=deployment.strategy_name,
        params=dict(deployment.params or {}),
        symbols=list(deployment.symbols or []),
        config=build_portfolio_config(deployment.starting_capital, deployment.config),
    )


def deterministic_client_id(
    deployment_id: int, trading_day: date, symbol: str, side: str
) -> str:
    """Idempotency key per (deployment, day, symbol, side)."""
    return f"dep{deployment_id}-{trading_day.isoformat()}-{symbol}-{side}"


# --- Pure cycle logic (BrokerPort + in-memory frames; no DB) ----------------


def state_from_broker(broker: BrokerPort, symbols: list[str]) -> PortfolioState:
    """Build the portfolio state from broker truth: cash from the account, a
    position per symbol from the broker's reported positions."""
    account = broker.get_account()
    positions: dict[str, PortfolioPosition] = {s: PortfolioPosition(symbol=s) for s in symbols}
    for pos in broker.get_positions():
        positions[pos.symbol] = PortfolioPosition(
            symbol=pos.symbol, quantity=pos.quantity, entry_price=pos.avg_entry_price
        )
    return PortfolioState(cash=account.cash, positions=positions)


def _decision_index(frame: pd.DataFrame, trading_day: date) -> int | None:
    """Index of the latest bar strictly before ``trading_day`` (the decision bar)."""
    idx: int | None = None
    for i, ts in enumerate(frame["timestamp"]):
        if pd.Timestamp(ts).date() < trading_day:
            idx = i
        else:
            break
    return idx


def _modeled_open(frame: pd.DataFrame, trading_day: date) -> float | None:
    """The backtest-modeled open for ``trading_day`` (the bar dated that day), or
    None if that bar is not yet ingested."""
    for _, row in frame.iterrows():
        if pd.Timestamp(row["timestamp"]).date() == trading_day:
            return float(row["open"])
    return None


def plan_cycle(
    broker: BrokerPort,
    spec: DeploymentSpec,
    frames: dict[str, pd.DataFrame],
    trading_day: date,
    *,
    peak_equity: float,
) -> CyclePlan:
    """Compute the orders to submit for ``trading_day`` from broker state, the
    strategy signals on the prior-session close, and the portfolio core. Pure."""
    config = spec.config
    symbols = sorted(frames)
    state = state_from_broker(broker, symbols)
    state.peak_equity = max(peak_equity, portfolio_equity(state, {}))

    contexts = {}
    marks: dict[str, float] = {}
    for sym in symbols:
        frame = frames[sym]
        idx = _decision_index(frame, trading_day)
        if idx is None:
            continue
        row = frame.iloc[idx]
        pos = state.positions.get(sym, PortfolioPosition(symbol=sym))
        # Resolve a FRESH strategy instance per symbol so a single-run stateful
        # strategy (e.g. the ML classifier, which carries ``_bars_held``) gets an
        # isolated counter and one symbol's state cannot bleed into another's
        # signal. The stateless rule strategies are unaffected (identical orders).
        strategy = resolve_strategy(spec.strategy_name, spec.params)
        decision = strategy.generate_signal(
            row, Position(quantity=pos.quantity, entry_price=pos.entry_price)
        )
        closes = frame["close"].to_numpy(dtype=float).tolist()
        contexts[sym] = build_symbol_context(sym, decision, closes, idx, config)
        marks[sym] = float(closes[idx])

    portfolio_decision = evaluate_portfolio(state, contexts, marks, config)

    planned: list[PlannedOrder] = []
    for order in portfolio_decision.orders:
        sym = order.symbol
        ref = marks.get(sym, 0.0)
        if order.side == "BUY":
            if ref <= 0.0:
                continue
            qty = float(math.floor(order.notional / ref))  # whole shares for OPG
            if qty < 1.0:
                continue
            side_enum = OrderSide.BUY
        else:  # SELL — close the full position
            qty = state.positions.get(sym, PortfolioPosition(symbol=sym)).quantity
            if qty <= 0.0:
                continue
            side_enum = OrderSide.SELL
        client_id = deterministic_client_id(spec.deployment_id, trading_day, sym, order.side)
        request = OrderRequest(
            symbol=sym, side=side_enum, quantity=qty,
            time_in_force=TimeInForce.OPG, client_order_id=client_id,
        )
        planned.append(
            PlannedOrder(
                request=request, symbol=sym, side=order.side, quantity=qty,
                notional=order.notional, reference_price=ref, reason=order.reason,
                client_order_id=client_id,
            )
        )

    return CyclePlan(
        orders=planned,
        halt_triggered=portfolio_decision.halt_triggered,
        halt_reason=portfolio_decision.halt_reason,
        decision_marks=marks,
        peak_equity=state.peak_equity,
    )


def submit_plan(broker: BrokerPort, plan: CyclePlan) -> dict[str, object]:
    """Submit each planned order (idempotent via client id). Returns a map of
    client_order_id → BrokerOrder."""
    submitted: dict[str, object] = {}
    for planned in plan.orders:
        broker_order = broker.submit_order(planned.request)
        submitted[planned.client_order_id] = broker_order
    return submitted


@dataclass(frozen=True)
class OrderRef:
    """The order fields reconciliation/attribution need, decoupled from whether
    the source is an in-memory plan or a persisted ``PaperOrder`` row."""

    client_order_id: str
    symbol: str
    side: str
    quantity: float
    reference_price: float


def order_refs_from_plan(plan: CyclePlan) -> list[OrderRef]:
    return [
        OrderRef(p.client_order_id, p.symbol, p.side, p.quantity, p.reference_price)
        for p in plan.orders
    ]


def order_refs_from_rows(rows: list[PaperOrder]) -> list[OrderRef]:
    return [
        OrderRef(o.client_order_id, o.symbol, o.side, o.intended_quantity, o.reference_price)
        for o in rows
    ]


def attribute_fills(
    broker: BrokerPort,
    orders: list[OrderRef],
    frames: dict[str, pd.DataFrame],
    trading_day: date,
) -> list[FillRecord]:
    """Read realized fills for these orders and attribute slippage against the
    backtest's modeled open (the fill-day bar's open), falling back to the decision
    reference price when that bar is not yet ingested.

    The slippage delta is signed by *cost*: positive = adverse. For a BUY that is
    ``fill - modeled`` (paid more than modeled); for a SELL it is ``modeled - fill``
    (received less than modeled). Pooled, the deltas read consistently across sides.
    """
    ref_by_client = {o.client_order_id: o.reference_price for o in orders}
    client_ids = set(ref_by_client)
    records: list[FillRecord] = []
    for fill in broker.list_fills():
        if fill.client_order_id not in client_ids:
            continue
        frame = frames.get(fill.symbol)
        modeled = _modeled_open(frame, trading_day) if frame is not None else None
        if modeled is None:
            modeled = ref_by_client.get(fill.client_order_id, fill.price)
        side = str(fill.side).upper()
        delta = (fill.price - modeled) if side == "BUY" else (modeled - fill.price)
        records.append(
            FillRecord(
                client_order_id=fill.client_order_id, broker_fill_id=fill.order_id,
                symbol=fill.symbol, side=side, quantity=fill.quantity,
                price=fill.price, modeled_reference_price=modeled,
                slippage_delta=delta, filled_at=fill.timestamp,
            )
        )
    return records


def reconcile(
    broker: BrokerPort, basket_symbols: list[str], orders: list[OrderRef]
) -> list[ReconRecord]:
    """Compare intended state to broker truth and record divergences. The broker's
    numbers are authoritative for accounting; this only flags what differs."""
    records: list[ReconRecord] = []
    # Order-level: rejects and partial fills against the intended quantity.
    for order in orders:
        broker_order = broker.get_order_by_client_id(order.client_order_id)
        if broker_order is None:
            continue
        if broker_order.status == OrderStatus.REJECTED:
            records.append(
                ReconRecord("reject", order.symbol,
                            f"{order.side} {order.quantity:g} rejected by broker.")
            )
        elif (
            broker_order.status.is_terminal
            and broker_order.filled_quantity + 1e-9 < order.quantity
        ):
            records.append(
                ReconRecord(
                    "partial_fill", order.symbol,
                    f"intended {order.quantity:g}, filled "
                    f"{broker_order.filled_quantity:g}.",
                )
            )
    # Position-level: a broker holding outside the deployment basket.
    basket = set(basket_symbols)
    for pos in broker.get_positions():
        if pos.symbol not in basket:
            records.append(
                ReconRecord("unexpected_position", pos.symbol,
                            f"broker holds {pos.quantity:g} {pos.symbol} not in basket.")
            )
    return records


def portfolio_snapshot_values(
    broker: BrokerPort, peak_equity: float
) -> dict[str, float | int]:
    """Portfolio snapshot fields from broker truth (broker is the source of truth)."""
    account = broker.get_account()
    positions = broker.get_positions()
    position_value = sum(p.market_value for p in positions)
    equity = account.equity
    peak = max(peak_equity, equity)
    drawdown_pct = ((peak - equity) / peak * 100.0) if peak > 0 else 0.0
    gross_pct = (position_value / equity * 100.0) if equity > 0 else 0.0
    return {
        "equity": equity,
        "cash": account.cash,
        "position_value": position_value,
        "gross_exposure_pct": gross_pct,
        "drawdown_pct": drawdown_pct,
        "peak_equity": peak,
        "num_positions": len(positions),
    }


# --- CRUD + kill-switch (DB) ------------------------------------------------


def create_deployment(
    db: Session,
    *,
    name: str,
    strategy_name: str,
    params: dict,
    symbols: list[str],
    starting_capital: float,
    config: dict,
    enabled: bool = True,
) -> PaperDeployment:
    """Persist a new deployment. Validates the strategy/params via the registry
    (a bad strategy or param raises a clean error, never a 500)."""
    resolve_strategy(strategy_name, params)  # validation only
    deployment = PaperDeployment(
        name=name, strategy_name=strategy_name, params=params, symbols=symbols,
        starting_capital=float(starting_capital), config=config, enabled=enabled,
        status="active",
    )
    db.add(deployment)
    db.flush()  # assign id before enforcing the single-enabled invariant
    if enabled:
        _disable_other_deployments(db, keep_id=deployment.id)
    db.commit()
    db.refresh(deployment)
    return deployment


def list_deployments(db: Session) -> list[PaperDeployment]:
    return list(db.scalars(select(PaperDeployment).order_by(PaperDeployment.id)).all())


def get_deployment(db: Session, deployment_id: int) -> PaperDeployment | None:
    return db.get(PaperDeployment, deployment_id)


def _disable_other_deployments(db: Session, keep_id: int) -> None:
    """Enforce the Phase 3 single-account invariant: at most one enabled
    deployment. Multiple enabled deployments would commingle cash on the one
    shared Alpaca paper account (plan §3.1 scopes Phase 3 to one deployment), so
    enabling one disables the rest."""
    for other in db.scalars(
        select(PaperDeployment).where(
            PaperDeployment.id != keep_id, PaperDeployment.enabled.is_(True)
        )
    ).all():
        other.enabled = False


def set_enabled(db: Session, deployment: PaperDeployment, enabled: bool) -> PaperDeployment:
    deployment.enabled = enabled
    if enabled:
        _disable_other_deployments(db, keep_id=deployment.id)
    db.commit()
    db.refresh(deployment)
    return deployment


def get_global_kill(db: Session) -> tuple[bool, str]:
    flag = db.get(SystemFlag, _GLOBAL_KILL_FLAG)
    if flag is None:
        return False, ""
    value = flag.value or {}
    return bool(value.get("active", False)), str(value.get("reason", ""))


def set_global_kill(db: Session, active: bool, reason: str = "") -> None:
    flag = db.get(SystemFlag, _GLOBAL_KILL_FLAG)
    if flag is None:
        flag = SystemFlag(name=_GLOBAL_KILL_FLAG, value={})
        db.add(flag)
    flag.value = {"active": bool(active), "reason": reason}
    db.commit()


def update_deployment(
    db: Session,
    deployment: PaperDeployment,
    *,
    name: str | None = None,
    params: dict | None = None,
    symbols: list[str] | None = None,
    starting_capital: float | None = None,
    config: dict | None = None,
) -> PaperDeployment:
    """Patch a deployment's definition (only provided fields). Re-validates the
    strategy/params via the registry."""
    if name is not None:
        deployment.name = name
    if params is not None:
        deployment.params = params
    if symbols is not None:
        deployment.symbols = symbols
    if starting_capital is not None:
        deployment.starting_capital = float(starting_capital)
    if config is not None:
        deployment.config = config
    resolve_strategy(deployment.strategy_name, deployment.params)  # validation
    db.commit()
    db.refresh(deployment)
    return deployment


# --- Read helpers for the dashboard / comparison ----------------------------


def portfolio_snapshots(db: Session, deployment_id: int) -> list[PortfolioSnapshot]:
    return list(
        db.scalars(
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.deployment_id == deployment_id)
            .order_by(PortfolioSnapshot.trading_day)
        ).all()
    )


def latest_positions(db: Session, deployment_id: int) -> list[PaperPositionSnapshot]:
    latest_day = db.scalar(
        select(func.max(PaperPositionSnapshot.trading_day)).where(
            PaperPositionSnapshot.deployment_id == deployment_id
        )
    )
    if latest_day is None:
        return []
    return list(
        db.scalars(
            select(PaperPositionSnapshot).where(
                PaperPositionSnapshot.deployment_id == deployment_id,
                PaperPositionSnapshot.trading_day == latest_day,
            )
        ).all()
    )


def recent_orders(db: Session, deployment_id: int, limit: int = 200) -> list[PaperOrder]:
    return list(
        db.scalars(
            select(PaperOrder)
            .where(PaperOrder.deployment_id == deployment_id)
            .order_by(PaperOrder.id.desc())
            .limit(limit)
        ).all()
    )


def recent_fills(db: Session, deployment_id: int, limit: int = 500) -> list[PaperFill]:
    return list(
        db.scalars(
            select(PaperFill)
            .where(PaperFill.deployment_id == deployment_id)
            .order_by(PaperFill.id.desc())
            .limit(limit)
        ).all()
    )


def recent_reconciliations(
    db: Session, deployment_id: int, limit: int = 200
) -> list[ReconciliationLog]:
    return list(
        db.scalars(
            select(ReconciliationLog)
            .where(ReconciliationLog.deployment_id == deployment_id)
            .order_by(ReconciliationLog.id.desc())
            .limit(limit)
        ).all()
    )


def slippage_stats(deltas: list[float]) -> dict[str, float | int]:
    """Distribution stats for the per-fill slippage deltas (pure)."""
    if not deltas:
        return {"count": 0, "mean": 0.0, "median": 0.0, "min": 0.0, "max": 0.0}
    return {
        "count": len(deltas),
        "mean": float(statistics.fmean(deltas)),
        "median": float(statistics.median(deltas)),
        "min": float(min(deltas)),
        "max": float(max(deltas)),
    }


def slippage_summary(db: Session, deployment_id: int) -> dict[str, float | int]:
    deltas = db.scalars(
        select(PaperFill.slippage_delta).where(
            PaperFill.deployment_id == deployment_id
        )
    ).all()
    return slippage_stats([float(d) for d in deltas])


def backtest_expectation(db: Session, deployment: PaperDeployment) -> Metrics | None:
    """Run the deployment's config through the M1 portfolio backtest over stored
    history — the backtested expectation shown beside the live results. None when
    there is no stored data for the basket yet."""
    spec = spec_from_deployment(deployment)
    frames = featured_frames(db, spec.symbols, date.today())
    if not frames:
        return None
    strategy = resolve_strategy(spec.strategy_name, spec.params)
    result = run_portfolio_backtest(frames, strategy, spec.config)
    return compute_portfolio_metrics(
        result.equity_curve, result.trades, spec.config.initial_capital
    )


def _peak_equity(db: Session, deployment: PaperDeployment) -> float:
    """The deployment's running equity peak from prior snapshots (else capital)."""
    rows = db.scalars(
        select(PortfolioSnapshot.peak_equity).where(
            PortfolioSnapshot.deployment_id == deployment.id
        )
    ).all()
    return max([*rows, deployment.starting_capital]) if rows else deployment.starting_capital


# --- DB orchestration -------------------------------------------------------


def featured_frames(
    db: Session, symbols: list[str], end_day: date
) -> dict[str, pd.DataFrame]:
    """Per-symbol featured OHLCV frames up to and including ``end_day``."""
    out: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        rows = query_market_data(db, sym, end=end_day)
        frame = orm_rows_to_frame(rows)
        if frame.empty:
            continue
        out[sym] = add_technical_indicators(frame)
    return out


@dataclass
class CycleResult:
    deployment_id: int
    trading_day: date
    skipped: str | None
    num_orders: int
    num_fills: int
    num_reconciliations: int
    halted: bool


def _guard_skip(db: Session, deployment: PaperDeployment, trading_day: date) -> str | None:
    """Shared pre-flight guards. Returns a skip reason or None to proceed."""
    kill_active, _ = get_global_kill(db)
    if kill_active:
        return "global_kill"
    if not deployment.enabled:
        return "disabled"
    if deployment.status == "halted":
        return "halted"
    return None


def run_submit_phase(
    db: Session, broker: BrokerPort, deployment: PaperDeployment, trading_day: date
) -> CycleResult:
    """Pre-open SUBMIT pass: decide on the prior-session close and place the
    opening-auction orders for ``trading_day``. Idempotent (deterministic client
    ids). Persists orders and a provisional snapshot; fills land later."""
    def _skip(reason: str) -> CycleResult:
        log.info("Paper submit dep=%s day=%s skipped: %s", deployment.id, trading_day, reason)
        return CycleResult(deployment.id, trading_day, reason, 0, 0, 0,
                           deployment.status == "halted")

    reason = _guard_skip(db, deployment, trading_day)
    if reason:
        return _skip(reason)
    if not _is_session(broker.get_clock(), trading_day):
        return _skip("market_closed")

    spec = spec_from_deployment(deployment)
    frames = featured_frames(db, spec.symbols, trading_day)
    if not frames:
        return _skip("no_data")

    peak = _peak_equity(db, deployment)
    plan = plan_cycle(broker, spec, frames, trading_day, peak_equity=peak)
    submit_plan(broker, plan)
    _persist_orders(db, broker, deployment, plan, trading_day)
    _persist_position_snapshots(db, broker, deployment, trading_day)
    _persist_portfolio_snapshot(db, broker, deployment, trading_day, plan.peak_equity)

    if plan.halt_triggered and deployment.status != "halted":
        deployment.status = "halted"
        deployment.halt_reason = plan.halt_reason
    db.commit()
    return CycleResult(deployment.id, trading_day, None, len(plan.orders), 0, 0,
                       deployment.status == "halted")


def run_reconcile_phase(
    db: Session, broker: BrokerPort, deployment: PaperDeployment, trading_day: date
) -> CycleResult:
    """Post-session RECONCILE pass: read the realized fills for ``trading_day``'s
    orders, attribute slippage against the now-ingested modeled open, reconcile
    against broker truth, and persist the final snapshots. No session guard — it
    runs after the close (and is re-runnable to correct attribution). Reads the
    persisted orders rather than re-planning, since broker state has since changed.
    """
    def _skip(reason: str) -> CycleResult:
        log.info("Paper reconcile dep=%s day=%s skipped: %s", deployment.id, trading_day, reason)
        return CycleResult(deployment.id, trading_day, reason, 0, 0, 0,
                           deployment.status == "halted")

    kill_active, _ = get_global_kill(db)
    if kill_active:
        return _skip("global_kill")
    if not deployment.enabled:
        return _skip("disabled")

    spec = spec_from_deployment(deployment)
    rows = list(
        db.scalars(
            select(PaperOrder).where(
                PaperOrder.deployment_id == deployment.id,
                PaperOrder.trading_day == trading_day,
            )
        ).all()
    )
    refs = order_refs_from_rows(rows)
    frames = featured_frames(db, spec.symbols, trading_day)

    fills = attribute_fills(broker, refs, frames, trading_day)
    _persist_fills(db, deployment, trading_day, fills)
    _refresh_order_status(db, broker, rows)

    recons = reconcile(broker, spec.symbols, refs)
    _persist_reconciliations(db, deployment, trading_day, recons)

    peak = _peak_equity(db, deployment)
    _persist_position_snapshots(db, broker, deployment, trading_day)
    _persist_portfolio_snapshot(db, broker, deployment, trading_day, peak)
    db.commit()
    return CycleResult(deployment.id, trading_day, None, len(rows), len(fills),
                       len(recons), deployment.status == "halted")


def run_paper_cycle(
    db: Session, broker: BrokerPort, deployment: PaperDeployment, trading_day: date
) -> CycleResult:
    """Convenience: the submit pass followed immediately by the reconcile pass.

    Used for a manual "run now" and for same-session flows (e.g. the FakeBroker,
    which fills on demand). In live operation the two passes are scheduled
    separately — submit pre-open, reconcile after the close and the next ingest —
    so slippage is attributed against the real modeled open."""
    submit = run_submit_phase(db, broker, deployment, trading_day)
    if submit.skipped is not None:
        return submit
    reconcile_result = run_reconcile_phase(db, broker, deployment, trading_day)
    return CycleResult(
        deployment_id=deployment.id, trading_day=trading_day, skipped=None,
        num_orders=submit.num_orders, num_fills=reconcile_result.num_fills,
        num_reconciliations=reconcile_result.num_reconciliations,
        halted=deployment.status == "halted",
    )


def _refresh_order_status(
    db: Session, broker: BrokerPort, rows: list[PaperOrder]
) -> None:
    """Refresh each persisted order's broker status/fill quantity from broker truth."""
    for row in rows:
        broker_order = broker.get_order_by_client_id(row.client_order_id)
        if broker_order is not None:
            row.broker_order_id = broker_order.id
            row.status = str(broker_order.status)
            row.filled_quantity = broker_order.filled_quantity


def _is_session(clock, trading_day: date) -> bool:
    """Whether ``trading_day`` is a market session. Uses the broker clock; when it
    carries no calendar info we treat it as a session (bar availability is the real
    gate). A closed market whose next open is on a *different* day is a non-session."""
    if clock.is_open:
        return True
    if clock.next_open is not None:
        return clock.next_open.date() == trading_day
    return True


def _persist_orders(
    db: Session, broker: BrokerPort, deployment: PaperDeployment,
    plan: CyclePlan, trading_day: date,
) -> None:
    for planned in plan.orders:
        existing = db.scalar(
            select(PaperOrder).where(
                PaperOrder.client_order_id == planned.client_order_id
            )
        )
        broker_order = broker.get_order_by_client_id(planned.client_order_id)
        if existing is not None:
            # Idempotent re-run: refresh the broker linkage and status.
            if broker_order is not None:
                existing.broker_order_id = broker_order.id
                existing.status = str(broker_order.status)
                existing.filled_quantity = broker_order.filled_quantity
            continue
        db.add(
            PaperOrder(
                deployment_id=deployment.id, trading_day=trading_day,
                client_order_id=planned.client_order_id,
                broker_order_id=broker_order.id if broker_order else None,
                symbol=planned.symbol, side=planned.side,
                intended_quantity=planned.quantity, intended_notional=planned.notional,
                reference_price=planned.reference_price,
                status=str(broker_order.status) if broker_order else "new",
                filled_quantity=broker_order.filled_quantity if broker_order else 0.0,
                reason=planned.reason,
                submitted_at=broker_order.submitted_at if broker_order else None,
            )
        )


def _persist_fills(
    db: Session, deployment: PaperDeployment, trading_day: date,
    fills: list[FillRecord],
) -> None:
    for fill in fills:
        order = db.scalar(
            select(PaperOrder).where(
                PaperOrder.client_order_id == fill.client_order_id
            )
        )
        if order is None:
            continue
        # Idempotency: a fill already recorded (same broker fill id + order) is
        # updated, not duplicated. The update lets a later reconcile pass *correct*
        # the slippage attribution once the fill-day bar has been ingested and the
        # true modeled open is available (it was a provisional fallback before).
        already = db.scalar(
            select(PaperFill).where(
                PaperFill.order_id == order.id,
                PaperFill.broker_fill_id == fill.broker_fill_id,
            )
        )
        if already is not None:
            already.modeled_reference_price = fill.modeled_reference_price
            already.slippage_delta = fill.slippage_delta
            already.filled_at = fill.filled_at
            continue
        db.add(
            PaperFill(
                deployment_id=deployment.id, order_id=order.id,
                broker_fill_id=fill.broker_fill_id, trading_day=trading_day,
                symbol=fill.symbol, side=fill.side, quantity=fill.quantity,
                price=fill.price, modeled_reference_price=fill.modeled_reference_price,
                slippage_delta=fill.slippage_delta, filled_at=fill.filled_at,
            )
        )


def _persist_reconciliations(
    db: Session, deployment: PaperDeployment, trading_day: date,
    recons: list[ReconRecord],
) -> None:
    for rec in recons:
        db.add(
            ReconciliationLog(
                deployment_id=deployment.id, trading_day=trading_day,
                kind=rec.kind, symbol=rec.symbol, detail=rec.detail,
            )
        )


def _persist_position_snapshots(
    db: Session, broker: BrokerPort, deployment: PaperDeployment, trading_day: date
) -> None:
    # Replace any existing snapshot rows for this day (idempotent re-run).
    for row in db.scalars(
        select(PaperPositionSnapshot).where(
            PaperPositionSnapshot.deployment_id == deployment.id,
            PaperPositionSnapshot.trading_day == trading_day,
        )
    ).all():
        db.delete(row)
    for pos in broker.get_positions():
        db.add(
            PaperPositionSnapshot(
                deployment_id=deployment.id, trading_day=trading_day,
                symbol=pos.symbol, quantity=pos.quantity,
                avg_entry_price=pos.avg_entry_price, market_value=pos.market_value,
                current_price=pos.current_price,
            )
        )


def _persist_portfolio_snapshot(
    db: Session, broker: BrokerPort, deployment: PaperDeployment,
    trading_day: date, peak_equity: float,
) -> None:
    values = portfolio_snapshot_values(broker, peak_equity)
    existing = db.scalar(
        select(PortfolioSnapshot).where(
            PortfolioSnapshot.deployment_id == deployment.id,
            PortfolioSnapshot.trading_day == trading_day,
        )
    )
    if existing is not None:
        for key, val in values.items():
            setattr(existing, key, val)
        return
    db.add(
        PortfolioSnapshot(
            deployment_id=deployment.id, trading_day=trading_day, **values
        )
    )
