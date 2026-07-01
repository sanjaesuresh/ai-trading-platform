"""News ablation harness — does news add alpha net of its cost? (Phase 5 M5/§6).

Train and walk-forward a **price-only** and a **price-plus-news** model on the
same symbols, splits, and costs, then test the increment honestly:

- Both arms route through the single-symbol battery (``evaluate_ml_walk_forward``),
  which has PBO + the Monte-Carlo ensemble + the full verdict — the leg where
  cross-symbol event co-movement most inflates a spurious edge.
- The news arm's deflated-Sharpe trial count is the price arm's N **multiplied by**
  the number of news-feature configurations tried (incl. prompt versions), so the
  larger search the news arm ran does not get a free pass on data-snooping.
- The increment is tested on its own: a paired stationary-bootstrap test on the
  per-bar (news − price) difference, deflated for the news search count, plus an
  explicit ``beats_price_only`` condition.
- LLM cost enters the **per-bar** return stream the significance battery sees — a
  daily drag from the actual billed annotation spend, charged to the news arm only
  (the correct asymmetry), not bolted onto the aggregate alone. A
  per-news-triggered-trade cost is reported alongside as a cross-check.
- The news-arm DSR is flagged as an upper bound: ESS deflates label overlap, which
  news doesn't change, but news features are autocorrelated and the same article
  hits many symbols — redundancy ESS does not deflate.

A null result is a valid, expected, shippable outcome.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from app.data.feature_engineering import add_technical_indicators
from app.ml.evaluation import (
    MLEvaluationResult,
    default_n_config_trials,
    evaluate_ml_walk_forward,
)
from app.ml.features import (
    FEATURE_COLUMNS,
    FeatureLabelSpec,
    build_features,
    build_pooled_panel,
)
from app.ml.news_features import (
    NEWS_FEATURE_COLUMNS,
    NEWS_FEATURE_SPEC_VERSION,
    build_news_features,
)
from app.ml.significance import (
    PairedIncrementalResult,
    paired_incremental_significance,
)
from app.ml.training import TrainingConfig

_DSR_UPPER_BOUND_CAVEAT = (
    "The news-arm deflated Sharpe is an upper bound, not a tight estimate: ESS "
    "deflates H-day label overlap (which news does not change), but decayed/"
    "autocorrelated news features and one article hitting many symbols carry "
    "redundancy ESS does not deflate."
)


@dataclass(frozen=True)
class AblationResult:
    """Price-only vs price-plus-news, with the honest incremental verdict."""

    eval_symbol: str
    price_arm: MLEvaluationResult
    news_arm: MLEvaluationResult
    price_n_trials: int
    news_n_trials: int
    n_news_configs_tried: int
    annotation_cost_usd: float
    daily_cost_drag: float  # per-bar return drag charged to the news arm
    cost_per_news_trade: float  # cross-check: spend / news-arm OOS round trips
    incremental: PairedIncrementalResult
    n_paired_bars: int
    dsr_caveat: str = _DSR_UPPER_BOUND_CAVEAT

    def to_dict(self) -> dict[str, object]:
        return {
            "eval_symbol": self.eval_symbol,
            "price_arm": self.price_arm.to_dict(),
            "news_arm": self.news_arm.to_dict(),
            "price_n_trials": int(self.price_n_trials),
            "news_n_trials": int(self.news_n_trials),
            "n_news_configs_tried": int(self.n_news_configs_tried),
            "annotation_cost_usd": float(self.annotation_cost_usd),
            "daily_cost_drag": float(self.daily_cost_drag),
            "cost_per_news_trade": float(self.cost_per_news_trade),
            "incremental": self.incremental.to_dict(),
            "n_paired_bars": int(self.n_paired_bars),
            "dsr_caveat": self.dsr_caveat,
        }


def _news_spec(horizon: int, deadband: float) -> FeatureLabelSpec:
    return FeatureLabelSpec(
        feature_columns=FEATURE_COLUMNS + NEWS_FEATURE_COLUMNS,
        horizon=horizon,
        deadband=deadband,
        news_version=NEWS_FEATURE_SPEC_VERSION,
    )


def _aligned_per_bar(
    price: MLEvaluationResult, news: MLEvaluationResult
) -> tuple[np.ndarray, np.ndarray]:
    """Concatenate the two arms' per-bar OOS model returns over the splits both ran.

    Pairing by (test_start, test_end) keeps the two streams aligned bar-for-bar even
    if one arm skipped a split the other kept (a single-class fold). Because news
    columns never drop a kept row, in practice the splits match exactly.
    """
    price_by_window = {
        (s.test_start, s.test_end): s.model.per_bar_returns for s in price.splits
    }
    news_by_window = {
        (s.test_start, s.test_end): s.model.per_bar_returns for s in news.splits
    }
    shared = sorted(set(price_by_window) & set(news_by_window))
    price_parts: list[float] = []
    news_parts: list[float] = []
    for window in shared:
        p = price_by_window[window]
        n = news_by_window[window]
        # Same OOS frame → equal per-bar length; guard defensively.
        length = min(len(p), len(n))
        price_parts.extend(p[:length])
        news_parts.extend(n[:length])
    return (
        np.asarray(price_parts, dtype="float64"),
        np.asarray(news_parts, dtype="float64"),
    )


def run_news_ablation(
    ohlcv_frames: dict[str, pd.DataFrame],
    annotations_by_symbol: dict[str, pd.DataFrame | None],
    *,
    eval_symbol: str,
    annotation_cost_usd: float,
    n_news_configs_tried: int,
    training_config: TrainingConfig | None = None,
    news_embargo: int = 1,
    relevance_threshold: float = 0.0,
    horizon: int = 5,
    in_sample_dates: int = 504,
    out_sample_dates: int = 126,
    step_dates: int = 126,
    fee_bps: float = 5.0,
    slippage_bps: float = 5.0,
    initial_capital: float = 100_000.0,
    mc_runs: int = 200,
    seed: int = 42,
) -> AblationResult:
    """Run the price-only vs price-plus-news ablation and return the honest verdict.

    ``ohlcv_frames`` maps each symbol to a raw OHLCV frame (timestamp + OHLCV);
    ``annotations_by_symbol`` maps each symbol to its article-level annotations
    (``published_at``, ``first_seen_at``, ``sentiment``, ``relevance``) or None.
    ``n_news_configs_tried`` is the number of news-feature configurations searched
    (decay, relevance cutoff, event threshold, taxonomy variant, prompt versions);
    it multiplies the price trial count for the news arm's deflated-Sharpe bar.
    """
    if n_news_configs_tried < 1:
        raise ValueError("n_news_configs_tried must be >= 1 (the news arm searched).")

    base_cfg = training_config or TrainingConfig()
    price_spec = replace(base_cfg.spec, horizon=horizon, news_version=None)
    news_spec = _news_spec(horizon, base_cfg.spec.deadband)
    price_cfg = replace(base_cfg, spec=price_spec)
    news_cfg = replace(base_cfg, spec=news_spec)

    indicator = {s: add_technical_indicators(f) for s, f in ohlcv_frames.items()}

    # Price arm.
    price_frames = {s: build_features(f) for s, f in indicator.items()}
    price_panel, _ = build_pooled_panel(indicator, spec=price_spec)

    # News arm: join annotations onto each indicator frame before featuring. News
    # columns are never NaN, so the keep-mask drops the same rows as price-only.
    news_indicator = {
        s: build_news_features(
            f,
            annotations_by_symbol.get(s),
            embargo=news_embargo,
            relevance_threshold=relevance_threshold,
        )
        for s, f in indicator.items()
    }
    news_frames = {s: build_features(f) for s, f in news_indicator.items()}
    news_panel, _ = build_pooled_panel(news_indicator, spec=news_spec)

    price_n_trials = default_n_config_trials(price_cfg)
    news_n_trials = price_n_trials * n_news_configs_tried

    wf_kwargs = {
        "eval_symbol": eval_symbol,
        "horizon": horizon,
        "in_sample_dates": in_sample_dates,
        "out_sample_dates": out_sample_dates,
        "step_dates": step_dates,
        "fee_bps": fee_bps,
        "slippage_bps": slippage_bps,
        "initial_capital": initial_capital,
        "mc_runs": mc_runs,
        "seed": seed,
    }
    price_arm = evaluate_ml_walk_forward(
        price_panel, price_frames, training_config=price_cfg,
        n_config_trials=price_n_trials, **wf_kwargs,  # type: ignore[arg-type]
    )
    news_arm = evaluate_ml_walk_forward(
        news_panel, news_frames, training_config=news_cfg,
        n_config_trials=news_n_trials, **wf_kwargs,  # type: ignore[arg-type]
    )

    price_pb, news_pb = _aligned_per_bar(price_arm, news_arm)
    n_bars = int(price_pb.size)

    # LLM cost as a daily drag on the news arm's per-bar stream (first-run billed
    # spend, charged to the news arm only — price-only incurs none).
    daily_drag = (
        annotation_cost_usd / initial_capital / n_bars if n_bars > 0 else 0.0
    )
    news_pb_net = news_pb - daily_drag
    diff = news_pb_net - price_pb

    incremental = paired_incremental_significance(
        diff, n_trials=news_n_trials, seed=seed
    )

    news_trades = sum(s.model.oos_round_trips for s in news_arm.splits)
    cost_per_trade = (
        annotation_cost_usd / news_trades if news_trades > 0 else float("nan")
    )

    return AblationResult(
        eval_symbol=eval_symbol,
        price_arm=price_arm,
        news_arm=news_arm,
        price_n_trials=price_n_trials,
        news_n_trials=news_n_trials,
        n_news_configs_tried=n_news_configs_tried,
        annotation_cost_usd=annotation_cost_usd,
        daily_cost_drag=daily_drag,
        cost_per_news_trade=cost_per_trade,
        incremental=incremental,
        n_paired_bars=n_bars,
    )
