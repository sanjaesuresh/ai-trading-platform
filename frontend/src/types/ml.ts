// ML pipeline types — mirror backend contracts (Phase 4 M4/M5).
// Results are simulated — not financial advice.

// ---------------------------------------------------------------------------
// Significance
// ---------------------------------------------------------------------------

export interface MLSignificanceBlock {
  sharpe: number
  skew: number
  kurtosis: number
  n_obs: number
  n_eff: number
  var_trial_sharpes: number
  deflated_sharpe: number
  pbo: number
  mc_percentile: number
  n_config_trials: number
  n_oos_round_trips: number
}

// ---------------------------------------------------------------------------
// Per-split result shapes
// ---------------------------------------------------------------------------

/** One strategy's OOS result on a single split (mirrors StrategyScore.to_dict). */
export interface MLStrategyScore {
  name: string
  /** Per-metric numeric values (sharpe_ratio, total_return_pct, etc.) */
  metrics: Record<string, number>
  turnover_annualized: number
  total_return_pct: number
  oos_round_trips: number
  per_bar_returns: number[]
}

/** One non-skipped walk-forward split (mirrors SplitResult.to_dict). */
export interface MLSplitResult {
  test_start: string
  test_end: string
  train_end: string
  oos_first_ts: string
  n_oos_bars: number
  no_look_ahead: boolean
  model: MLStrategyScore
  baselines: Record<string, MLStrategyScore>
  mc_returns: number[]
  mc_mean_turnover: number
  classification: { auc: number; brier: number }
  beats: Record<string, boolean>
}

/** A split skipped because the model could not be trained (mirrors SkippedSplit.to_dict). */
export interface MLSkippedSplit {
  test_start: string
  test_end: string
  reason: string
}

// ---------------------------------------------------------------------------
// Walk-forward result (stored in EvaluationRun.results JSON)
// ---------------------------------------------------------------------------

export type MLVerdict = 'pass' | 'fail' | 'inconclusive'

/** The complete walk-forward verdict (mirrors MLEvaluationResult.to_dict). */
export interface MLWalkForwardResult {
  eval_symbol: string
  verdict: MLVerdict
  reasons: string[]
  significance: MLSignificanceBlock
  /**
   * Aggregate model metrics keyed by name.
   * Keys: total_return_pct, per_period_sharpe, num_oos_round_trips,
   * mean_turnover_annualized, mc_mean_turnover_annualized,
   * beats_buy_and_hold, beats_rule, beats_logistic,
   * splits_beating_buy_and_hold, splits_beating_rule, splits_beating_logistic,
   * n_splits_evaluated.
   */
  aggregate_model: Record<string, number>
  /** Aggregate baseline metrics. Keys: buy_and_hold, rule, logistic_floor. */
  aggregate_baselines: Record<string, Record<string, number>>
  splits: MLSplitResult[]
  skipped: MLSkippedSplit[]
}

// ---------------------------------------------------------------------------
// Model registry
// ---------------------------------------------------------------------------

export interface MLModelSummary {
  id: number
  model_id: string
  feature_spec_version: string
  symbols: string[]
  train_start: string
  train_end: string
  horizon: number
  deadband: number
  calibrated: boolean
  enter_threshold: number
  exit_threshold: number
  created_at: string
}

export interface MLModelDetail extends MLModelSummary {
  lgbm_params: Record<string, unknown>
  seed: number
  num_threads: number
  calibration: string
  min_hold: number
  n_fit: number
  n_calib: number
  n_thresh: number
  effective_n: number
  selection_config: Record<string, unknown>
  validation_metrics: Record<string, unknown>
  code_git_hash: string
  code_dirty: boolean
  code_diff_hash: string | null
  artifact_hash: string
}

// ---------------------------------------------------------------------------
// API request shapes
// ---------------------------------------------------------------------------

export interface MLWalkForwardRequest {
  symbols: string[]
  eval_symbol: string
  scheme?: 'anchored' | 'rolling'
  in_sample_dates?: number
  out_sample_dates?: number
  step_dates?: number
  horizon?: number
  deadband?: number
  fee_bps?: number
  slippage_bps?: number
  initial_capital?: number
  mc_runs?: number
  seed?: number
}

// ---------------------------------------------------------------------------
// Evaluation summary / detail (mirrors MLEvaluationSummary / MLEvaluationDetail)
// ---------------------------------------------------------------------------

export interface MLEvaluationSummary {
  id: number
  kind: string
  symbol: string
  strategy_name: string
  status: string
  objective: string
  created_at: string
}

export interface MLEvaluationDetail extends MLEvaluationSummary {
  config: Record<string, unknown>
  /** Empty object when the run is still queued/running; full result when completed. */
  results: Partial<MLWalkForwardResult>
}
