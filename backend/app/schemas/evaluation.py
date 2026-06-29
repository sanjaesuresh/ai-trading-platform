"""Request/response contracts for evaluation runs (sweeps + walk-forward).

The request engine knobs mirror ``RunRequest`` so a sweep evaluates the same
strategy under the same fees, slippage, sizing, and risk controls as a single
backtest — every comparison stays net of fees. ``max_combinations`` is the size
guard: a grid that expands past it is rejected with a clean 4xx, never silently
truncated.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Objectives the runner may select/rank on. Constrained to higher-is-better
# metric fields: selection maximizes the objective, so a "lower-is-better" field
# (max_drawdown_pct, avg_loss) would silently pick the *worst* combination. A
# field not in this set (or a typo) is rejected at the request boundary (422)
# rather than raising deep in the run via getattr.
Objective = Literal[
    "sharpe_ratio",
    "sortino_ratio",
    "total_return_pct",
    "annualized_return_pct",
    "profit_factor",
    "win_rate",
]


class SweepRequest(BaseModel):
    """Inputs to a parameter sweep over a strategy's grid.

    Data source mirrors ``RunRequest``: provide ``csv_path`` for CSV mode, or omit
    it to read stored adjusted bars for ``symbol`` (DB mode).
    """

    symbol: str = Field(min_length=1, max_length=32)
    csv_path: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "Path under the allowed data directory (CSV mode). "
            "Omit to read from the database using ``symbol`` (DB mode)."
        ),
    )
    strategy_name: str = Field(
        default="trend_following",
        min_length=1,
        max_length=64,
        description="Registered strategy name; see GET /strategies.",
    )
    param_grid: dict[str, list] = Field(
        default_factory=dict,
        description=(
            "Map of param name → list of values to sweep. The Cartesian product is "
            "evaluated; an empty grid runs the strategy's own defaults once."
        ),
    )
    objective: Objective = Field(
        default="sharpe_ratio",
        description="Higher-is-better metric to select/rank on; see Objective for the set.",
    )
    max_combinations: int = Field(
        default=200,
        ge=1,
        description="Reject (4xx) a grid that expands past this many combinations.",
    )

    # --- engine run params, mirroring RunRequest ---
    initial_capital: float = Field(default=100_000.0, gt=0)
    fee_bps: float = Field(default=5.0, ge=0, le=1_000)
    slippage_bps: float = Field(default=5.0, ge=0, le=1_000)
    max_position_pct: float = Field(default=0.95, gt=0, le=1.0)
    target_vol: float | None = Field(default=None, gt=0)
    vol_lookback: int = Field(default=20, ge=2)
    stop_loss_pct: float | None = Field(default=None, gt=0, le=1.0)
    take_profit_pct: float | None = Field(default=None, gt=0)
    max_drawdown_cutoff_pct: float | None = Field(default=None, gt=0, le=1.0)


class WalkForwardRequest(SweepRequest):
    """A sweep plus an out-of-sample walk-forward policy and a baseline to beat."""

    scheme: Literal["anchored", "rolling"] = Field(
        default="anchored",
        description="anchored = expanding in-sample window; rolling = fixed-length window.",
    )
    in_sample_size: int = Field(default=504, ge=2, description="Training bars per split.")
    out_sample_size: int = Field(default=126, ge=2, description="Test bars per split.")
    step: int = Field(default=126, ge=1, description="Bars to advance the window each split.")
    baseline_strategy_name: str = Field(
        default="trend_following",
        min_length=1,
        max_length=64,
        description="Rule-based baseline run out-of-sample for comparison.",
    )
    baseline_params: dict = Field(
        default_factory=dict,
        description="Parameters for the baseline strategy (defaults when empty).",
    )


class EvaluationSummary(BaseModel):
    """One row in the evaluations list."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    symbol: str
    strategy_name: str
    status: str
    objective: str
    created_at: datetime


class EvaluationDetail(EvaluationSummary):
    """Full evaluation detail: summary plus the request config and results blob."""

    config: dict
    results: dict
