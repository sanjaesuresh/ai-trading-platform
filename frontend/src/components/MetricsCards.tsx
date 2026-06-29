import type { RunDetail } from '../types/backtest'
import {
  formatCurrency,
  formatPercent,
  formatFraction,
  formatProfitFactor,
  returnClass,
} from '../utils/format'

interface MetricsCardsProps {
  run: RunDetail
}

interface Card {
  label: string
  value: string
  cls: string
  note?: string
}

export function MetricsCards({ run }: MetricsCardsProps) {
  const { metrics, final_equity, num_trades } = run

  const sharpeClass =
    metrics.sharpe_ratio >= 1
      ? 'text-emerald-400'
      : metrics.sharpe_ratio < 0
        ? 'text-rose-400'
        : 'text-zinc-50'

  const pfClass =
    metrics.profit_factor >= 1.5
      ? 'text-emerald-400'
      : metrics.profit_factor < 1
        ? 'text-rose-400'
        : 'text-zinc-50'

  const cards: Card[] = [
    {
      label: 'Total Return',
      value:
        (metrics.total_return_pct > 0 ? '+' : '') +
        formatPercent(metrics.total_return_pct),
      cls: returnClass(metrics.total_return_pct),
    },
    {
      label: 'Final Equity',
      value: formatCurrency(final_equity),
      cls: 'text-zinc-50',
    },
    {
      label: 'Max Drawdown',
      value: `−${formatPercent(metrics.max_drawdown_pct)}`,
      cls: 'text-rose-400',
      note: 'peak-to-trough',
    },
    {
      label: 'Sharpe Ratio',
      value: metrics.sharpe_ratio.toFixed(2),
      cls: sharpeClass,
    },
    {
      label: 'Win Rate',
      value: formatFraction(metrics.win_rate),
      cls: 'text-zinc-50',
      note: `${metrics.num_round_trips} round trips`,
    },
    {
      label: 'Profit Factor',
      value: formatProfitFactor(metrics.profit_factor),
      cls: pfClass,
    },
    {
      label: 'Total Trades',
      value: String(num_trades),
      cls: 'text-zinc-50',
    },
  ]

  return (
    <dl className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {cards.map((card) => (
        <div
          key={card.label}
          className="bg-zinc-900 border border-zinc-800 rounded p-4"
        >
          <dt className="text-xs font-medium text-zinc-500 uppercase tracking-wider mb-2">
            {card.label}
          </dt>
          <dd className={`text-xl font-mono font-semibold ${card.cls}`}>
            {card.value}
          </dd>
          {card.note !== undefined && (
            <p className="text-xs text-zinc-600 mt-1">{card.note}</p>
          )}
        </div>
      ))}
    </dl>
  )
}
