---
name: add-strategy
description: Add a new trading strategy to this platform correctly — under the BaseStrategy interface, with leakage-safe signal logic, fees/slippage-aware evaluation against the rule-based baseline, and the required tests. Use when the user says "add a strategy", "new strategy", "implement mean-reversion / breakout / momentum", "register a strategy", or wants to extend the backtester with another rule set. Project-scoped to ai-trading-platform.
---

# Add a strategy to the AI Trading Platform

This is the repo-specific procedure for adding a strategy. It encodes the
platform's contracts and its non-negotiable correctness rules so a new strategy
slots in without breaking the backtest's honesty guarantees. Plain-English
planning first per the project's planning gate — no code until the approach is
agreed.

## Before you touch code

1. **Read the contracts that already exist.** A strategy is only correct
   relative to the interfaces it plugs into. Read, in this order:
   - `backend/app/strategies/base_strategy.py` — the `StrategySignal` enum
     (BUY / SELL / HOLD), the `StrategyDecision` value object (timestamp,
     symbol, action, confidence, reason, metadata), and the abstract
     `BaseStrategy.generate_signal(row, current_position)` contract.
   - `backend/app/strategies/trend_following.py` — the reference implementation.
     Match its style, its confidence-scoring shape, and its readable-`reason`
     convention.
   - `backend/app/backtesting/engine.py` — how the engine calls the strategy
     bar by bar, what columns the `row` actually carries, and how
     `current_position` is represented.
   - `backend/app/data/feature_engineering.py` — the exact indicator columns
     available (returns, log returns, SMA-20/50, EMA-20, RSI-14, MACD + signal,
     Bollinger upper/lower, ATR-14, rolling vol-20, volume MA-20). A strategy
     may only read columns this module produces; if you need a new indicator,
     add it here first (see step 4).

2. **Write the strategy spec as prose and get it approved.** Per the project
   planning gate, a new strategy is medium+ work. Capture: the entry rule, the
   exit rule, how confidence is scored, what the `reason` sentence says, which
   indicator columns it reads, and what new indicators (if any) are needed.
   State it in plain English. Do not write code until the user approves.

## The correctness rules a strategy MUST obey

These are the reasons the backtest can be trusted. Violating any of them
silently corrupts every result the strategy produces.

- **No look-ahead.** `generate_signal` may read only the current `row` and
  `current_position`. It must never peek at future bars, the full series, or any
  value that would not have been known at that bar's close. The engine fills the
  resulting order at the **next bar's open** — the strategy must not assume it
  trades at the close that produced the signal.
- **Indicators are past-only.** Every column the strategy reads must be
  computable from data up to and including the current bar. Indicators added in
  `feature_engineering.py` must use trailing windows only — never centered or
  forward-looking windows, never `.shift(-n)`.
- **Warm-up NaNs are real.** Early bars where an indicator is undefined arrive as
  NaN. The strategy must return HOLD (or the engine skips the row) rather than
  trading on a NaN-derived comparison. Decide explicitly what happens during
  warm-up.
- **Long-only, one position, no shorting/margin** (Phase 1 engine). A SELL with
  no open position and a BUY while already long are both no-ops by the engine's
  rules; the strategy should not rely on behavior outside this.
- **The `reason` is always a non-empty, readable sentence** naming the conditions
  that drove the decision. This is a tested invariant and it is what makes a run
  auditable.

## Implementation steps (after approval)

1. **New indicators first, if needed.** Add them to
   `feature_engineering.py` as a non-mutating transform (return a new frame),
   trailing-window only. Extend `test_feature_engineering.py` to assert the new
   columns exist and the input frame is not mutated.

2. **Create `backend/app/strategies/<your_strategy>.py`.** Subclass
   `BaseStrategy`, set a unique `name`, implement `generate_signal`. Mirror the
   trend-following file's structure: clear entry/exit conditions, a confidence
   that grows per confirming condition and caps below 1.0, and a `reason` that
   names the firing conditions.

3. **Register it** wherever strategies are resolved (today the service wires the
   trend-following strategy directly in `services/backtest_service.py`; if a
   strategy registry exists per the Phase 2 roadmap, register there instead).
   Keep the dispatch one obvious place.

4. **Tests are required** — add `test_<your_strategy>.py` next to the existing
   strategy test. At minimum, mirror `test_trend_following_strategy.py`:
   - a constructed bar matching the entry rule yields BUY,
   - a bar matching the exit rule yields SELL,
   - a neutral bar yields HOLD,
   - the `reason` is always non-empty,
   - warm-up / NaN rows yield HOLD and never raise.
   Tests run on pure in-memory frames with no database.

## Evaluation discipline — a strategy is not "done" because it runs

A backtest that looks profitable is the default trap, not the goal. Before
claiming a strategy is good:

- Evaluate **net of fees and slippage**, not gross. The engine already applies
  both; never report gross returns.
- Compare against the **rule-based trend-following baseline** on the same data.
  Beating buy-and-hold and beating the baseline are different bars; state which.
- Be honest about **overfitting**. If you tuned thresholds to make the sample
  data look good, say so — that is in-sample fitting, not edge. The roadmap
  defers parameter sweeps and walk-forward to Phase 2 for exactly this reason;
  do not fake rigor the platform doesn't have yet.
- Keep the **simulated-only framing**. No result here implies real-world
  returns, and nothing the strategy emits is advice.

## Verify before declaring done

Run the real checks and see them pass:

- `cd backend && ruff check . && ruff format --check .`
- `cd backend && mypy app` (pragmatic on pandas-heavy code)
- `cd backend && pytest` — the new strategy test green alongside the existing five
- A sample backtest runs end to end and persists a run with trades

When the strategy logic is non-trivial, hand the diff to the
`backtest-integrity-reviewer` agent (look-ahead / leakage) and the
`quant-strategy-reviewer` agent (logic + evaluation rigor) before merging.
