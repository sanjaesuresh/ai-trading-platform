import type { RunDetail } from '../types/backtest'
import { Stat, StatGrid, SectionHeader } from './ui'
import { MetricStat } from './MetricStat'
import { formatCurrency } from '../utils/format'

interface MetricsCardsProps {
  run: RunDetail
}

/**
 * Full performance readout for a backtest, grouped so the reader can scan by
 * concern: how capital grew, how risky the path was, and how the individual
 * trades behaved. Every value is defined inline via the metric definitions.
 */
export function MetricsCards({ run }: MetricsCardsProps) {
  const m = run.metrics

  return (
    <div className="space-y-6">
      <section aria-labelledby="metrics-returns">
        <SectionHeader
          id="metrics-returns"
          title="Returns"
          subtitle="Growth of capital over the period, net of fees and slippage."
        />
        <StatGrid>
          <MetricStat metricKey="total_return_pct" value={m.total_return_pct} />
          <MetricStat metricKey="annualized_return_pct" value={m.annualized_return_pct} />
          <Stat
            label="Final Equity"
            value={formatCurrency(run.final_equity)}
            hint={`From ${formatCurrency(run.initial_capital)} initial capital.`}
          />
          <MetricStat metricKey="exposure_pct" value={m.exposure_pct} />
        </StatGrid>
      </section>

      <section aria-labelledby="metrics-risk">
        <SectionHeader
          id="metrics-risk"
          title="Risk"
          subtitle="How bumpy the ride was, and whether gains outweighed losses."
        />
        <StatGrid>
          <MetricStat metricKey="max_drawdown_pct" value={m.max_drawdown_pct} />
          <MetricStat metricKey="sharpe_ratio" value={m.sharpe_ratio} />
          <MetricStat metricKey="sortino_ratio" value={m.sortino_ratio} />
          <MetricStat metricKey="profit_factor" value={m.profit_factor} />
        </StatGrid>
      </section>

      <section aria-labelledby="metrics-trades">
        <SectionHeader
          id="metrics-trades"
          title="Trade Stats"
          subtitle="Behavior of individual round-trip trades (entry paired with exit)."
        />
        <StatGrid cols="grid-cols-2 md:grid-cols-3 lg:grid-cols-6">
          <MetricStat metricKey="win_rate" value={m.win_rate} />
          <MetricStat metricKey="num_round_trips" value={m.num_round_trips} />
          <MetricStat metricKey="avg_win" value={m.avg_win} />
          <MetricStat metricKey="avg_loss" value={m.avg_loss} />
          <MetricStat metricKey="avg_holding_days" value={m.avg_holding_days} />
          <MetricStat metricKey="num_fills" value={m.num_fills} />
        </StatGrid>
      </section>
    </div>
  )
}
