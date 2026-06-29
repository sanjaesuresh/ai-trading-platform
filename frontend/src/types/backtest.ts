export interface RunRequest {
  symbol: string
  // Omit for DB mode (read stored bars for `symbol`); set a path under the
  // allowed data directory for CSV mode.
  csv_path?: string
  strategy_name?: string
  strategy_params?: Record<string, number>
  initial_capital: number
  fee_bps: number
  slippage_bps: number
  max_position_pct: number
  // Optional Phase 2 sizing / risk controls; null or omitted = disabled.
  target_vol?: number | null
  vol_lookback?: number
  stop_loss_pct?: number | null
  take_profit_pct?: number | null
  max_drawdown_cutoff_pct?: number | null
}

export interface RunSummary {
  id: number
  symbol: string
  strategy_name: string
  status: string
  initial_capital: number
  final_equity: number
  total_return_pct: number
  max_drawdown_pct: number
  sharpe_ratio: number
  win_rate: number
  num_trades: number
  created_at: string
}

export interface Metrics {
  total_return_pct: number
  annualized_return_pct: number
  max_drawdown_pct: number
  sharpe_ratio: number
  sortino_ratio: number
  win_rate: number
  profit_factor: number
  num_round_trips: number
  num_fills: number
  avg_win: number
  avg_loss: number
  avg_holding_days: number
  exposure_pct: number
}

export interface EquityPoint {
  timestamp: string
  equity: number
  cash: number
  position_value: number
}

export interface Trade {
  symbol: string
  side: string
  timestamp: string
  price: number
  quantity: number
  gross_value: number
  fee: number
  slippage: number
  cash_after: number
  position_after: number
  equity_after: number
  reason: string
}

export interface RunDetail extends RunSummary {
  config: Record<string, unknown>
  metrics: Metrics
  equity_curve: EquityPoint[]
  trades: Trade[]
}
