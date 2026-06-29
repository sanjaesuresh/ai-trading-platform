// Evaluation types — mirror the backend evaluation contracts (sweeps +
// walk-forward). Results are reported as a full out-of-sample distribution, never
// a single best cell; see EvaluationResults.

import type { Metrics } from './backtest'

export type EvaluationObjective =
  | 'sharpe_ratio'
  | 'sortino_ratio'
  | 'total_return_pct'
  | 'annualized_return_pct'
  | 'profit_factor'
  | 'win_rate'

export interface SweepRequest {
  symbol: string
  csv_path?: string
  strategy_name?: string
  param_grid?: Record<string, number[]>
  objective?: EvaluationObjective
  max_combinations?: number
  initial_capital?: number
  fee_bps?: number
  slippage_bps?: number
  max_position_pct?: number
  target_vol?: number | null
  vol_lookback?: number
  stop_loss_pct?: number | null
  take_profit_pct?: number | null
  max_drawdown_cutoff_pct?: number | null
}

export interface WalkForwardRequest extends SweepRequest {
  scheme?: 'anchored' | 'rolling'
  in_sample_size?: number
  out_sample_size?: number
  step?: number
  baseline_strategy_name?: string
  baseline_params?: Record<string, number>
}

export interface EvaluationSummary {
  id: number
  kind: string // "sweep" | "walk_forward"
  symbol: string
  strategy_name: string
  status: string // queued | running | completed | failed
  objective: string
  created_at: string
}

// best/median/worst are over the out-of-sample objective when one exists. A bare
// sweep is in-sample only (is_out_of_sample = false) — not out-of-sample evidence.
export interface DistributionSummary {
  objective: string
  best: number
  median: number
  worst: number
  best_params: Record<string, number>
  // null = no baseline ran (a pure sweep); distinct from 0 (a baseline ran and
  // nothing beat it).
  pct_beating_baseline: number | null
  in_sample_vs_out_sample_gap: number
  overfit_flag: boolean
  is_out_of_sample: boolean
}

export interface CombinationResult {
  params: Record<string, number>
  in_sample: Metrics
  out_sample: Metrics | null
  num_trades_in: number
  num_trades_out: number
}

export interface SplitResult {
  train_start: number
  train_end: number
  test_start: number
  test_end: number
  chosen_params: Record<string, number>
  in_sample: Metrics
  out_sample: Metrics
  baseline_out_sample: Metrics
  num_trades_in: number
  num_trades_out: number
}

// The walk-forward summary can be empty ({}) when no split fit the data, so the
// summary fields are treated as optional by consumers.
export interface EvaluationResults {
  summary: Partial<DistributionSummary>
  n_combinations: number
  caveat: string
  combinations?: CombinationResult[]
  splits?: SplitResult[]
}

export interface EvaluationDetail extends EvaluationSummary {
  config: Record<string, unknown>
  results: EvaluationResults
}
