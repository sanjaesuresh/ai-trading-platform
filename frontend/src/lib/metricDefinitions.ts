import type { Metrics } from '../types/backtest'
import {
  formatCurrency,
  formatPercent,
  formatSignedPercent,
  formatFraction,
  formatProfitFactor,
} from '../utils/format'

export type Tone = 'pos' | 'neg' | 'default'

export interface MetricDef {
  /** Short human label (Inter UI text). */
  label: string
  /** One-line plain-English definition shown as the stat's caption. */
  definition: string
  /** Unit suffix rendered next to the value, when useful. */
  unit?: string
  /** Format a raw numeric value into its display string. */
  format: (value: number) => string
  /** Color the value carries, derived from its own magnitude. */
  tone?: (value: number) => Tone
}

const signedReturnTone = (v: number): Tone =>
  v > 0 ? 'pos' : v < 0 ? 'neg' : 'default'

/**
 * Single source of truth for what each performance metric means, how it is
 * formatted, and what color it carries. Consumed by the backtest metric grid,
 * the evaluation distribution stats, and the paper-vs-backtest comparison so a
 * definition never drifts between surfaces.
 */
export const METRIC_DEFS: Record<keyof Metrics, MetricDef> = {
  total_return_pct: {
    label: 'Total Return',
    definition: 'Cumulative percent change in equity over the full period.',
    format: formatSignedPercent,
    tone: signedReturnTone,
  },
  annualized_return_pct: {
    label: 'Annualized Return',
    definition: 'Total return scaled to a yearly rate (CAGR).',
    format: formatSignedPercent,
    tone: signedReturnTone,
  },
  max_drawdown_pct: {
    label: 'Max Drawdown',
    definition: 'Largest peak-to-trough equity decline over the period.',
    format: (v) => (v === 0 ? formatPercent(v) : `−${formatPercent(v)}`),
    tone: () => 'neg',
  },
  sharpe_ratio: {
    label: 'Sharpe Ratio',
    definition: 'Return per unit of total volatility, annualized. Risk-free 0.',
    format: (v) => v.toFixed(2),
    tone: (v) => (v >= 1 ? 'pos' : v < 0 ? 'neg' : 'default'),
  },
  sortino_ratio: {
    label: 'Sortino Ratio',
    definition: 'Like Sharpe, but penalizes only downside volatility.',
    format: (v) => v.toFixed(2),
    tone: (v) => (v >= 1 ? 'pos' : v < 0 ? 'neg' : 'default'),
  },
  win_rate: {
    label: 'Win Rate',
    definition: 'Share of round-trip trades that closed profitable.',
    format: formatFraction,
  },
  profit_factor: {
    label: 'Profit Factor',
    definition: 'Gross profit ÷ gross loss. Above 1 is net positive.',
    format: formatProfitFactor,
    tone: (v) => (v >= 1.5 ? 'pos' : v < 1 ? 'neg' : 'default'),
  },
  num_round_trips: {
    label: 'Round Trips',
    definition: 'Completed entry-to-exit trade pairs.',
    format: (v) => String(v),
  },
  num_fills: {
    label: 'Fills',
    definition: 'Individual order executions (buys + sells).',
    format: (v) => String(v),
  },
  avg_win: {
    label: 'Avg Win',
    definition: 'Mean profit of winning round trips.',
    format: formatCurrency,
    tone: (v) => (v > 0 ? 'pos' : 'default'),
  },
  avg_loss: {
    label: 'Avg Loss',
    definition: 'Mean loss of losing round trips.',
    format: formatCurrency,
    tone: (v) => (v < 0 ? 'neg' : 'default'),
  },
  avg_holding_days: {
    label: 'Avg Holding',
    definition: 'Mean days a position was held per round trip.',
    unit: 'days',
    format: (v) => v.toFixed(1),
  },
  exposure_pct: {
    label: 'Exposure',
    definition: 'Share of bars with an open position (time in market).',
    format: formatPercent,
  },
}

/** Format one metric value using its canonical definition. */
export function formatMetric(key: keyof Metrics, value: number): string {
  return METRIC_DEFS[key].format(value)
}

/** Resolve the tone (pos/neg/default) for one metric value. */
export function metricTone(key: keyof Metrics, value: number): Tone {
  return METRIC_DEFS[key].tone?.(value) ?? 'default'
}
