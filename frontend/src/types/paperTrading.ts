// Paper-trading types (Phase 3 M5), mirroring app/schemas/paper_trading.py.
// Simulated paper trading only — no real money is traded.

export interface DeploymentRiskConfig {
  fee_bps: number
  slippage_bps: number
  target_vol: number | null
  vol_lookback: number
  max_position_pct: number
  gross_exposure_cap: number
  max_open_positions: number
  per_order_notional_cap: number | null
  stop_loss_pct: number | null
  take_profit_pct: number | null
  max_drawdown_cutoff_pct: number | null
}

export interface DeploymentCreateRequest {
  name: string
  strategy_name: string
  params: Record<string, number>
  symbols: string[]
  starting_capital: number
  config: DeploymentRiskConfig
  enabled: boolean
}

export interface DeploymentSummary {
  id: number
  name: string
  strategy_name: string
  symbols: string[]
  starting_capital: number
  enabled: boolean
  status: string
  halt_reason: string | null
  created_at: string
  updated_at: string
}

export interface DeploymentDetail extends DeploymentSummary {
  params: Record<string, number>
  config: DeploymentRiskConfig
}

export interface PortfolioSnapshot {
  trading_day: string
  equity: number
  cash: number
  position_value: number
  gross_exposure_pct: number
  drawdown_pct: number
  peak_equity: number
  num_positions: number
}

export interface Position {
  trading_day: string
  symbol: string
  quantity: number
  avg_entry_price: number
  market_value: number
  current_price: number
}

export interface Order {
  id: number
  trading_day: string
  symbol: string
  side: string
  intended_quantity: number
  intended_notional: number
  reference_price: number
  status: string
  filled_quantity: number
  reason: string
  submitted_at: string | null
}

export interface Fill {
  id: number
  trading_day: string
  symbol: string
  side: string
  quantity: number
  price: number
  modeled_reference_price: number
  slippage_delta: number
  filled_at: string | null
}

export interface Recon {
  id: number
  trading_day: string
  kind: string
  symbol: string | null
  detail: string
  created_at: string
}

export interface SlippageSummary {
  count: number
  mean: number
  median: number
  min: number
  max: number
}

export interface KillSwitchStatus {
  active: boolean
  reason: string
}

export interface PortfolioView {
  deployment: DeploymentDetail
  equity_curve: PortfolioSnapshot[]
  positions: Position[]
  orders: Order[]
  fills: Fill[]
  reconciliations: Recon[]
  slippage: SlippageSummary
  global_kill: KillSwitchStatus
  disclaimer: string
}

export interface MetricsOut {
  total_return_pct: number
  annualized_return_pct: number
  max_drawdown_pct: number
  sharpe_ratio: number
  sortino_ratio: number
  win_rate: number
  profit_factor: number
  num_round_trips: number
}

export interface ComparisonView {
  deployment_id: number
  backtest_expectation: MetricsOut | null
  live_equity_curve: PortfolioSnapshot[]
  slippage: SlippageSummary
  caveat: string
  disclaimer: string
}

export interface RunTriggerResponse {
  job_id: string | null
  status: string
  deployment_id: number
  phase: string
  trading_day: string | null
}
