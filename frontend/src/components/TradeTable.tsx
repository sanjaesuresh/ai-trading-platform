import type { Trade } from '../types/backtest'
import { formatCurrency, formatDate } from '../utils/format'

interface TradeTableProps {
  trades: Trade[]
}

export function TradeTable({ trades }: TradeTableProps) {
  if (trades.length === 0) {
    return (
      <div className="flex items-center justify-center py-12 text-zinc-500 text-sm">
        No trades recorded for this backtest.
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-zinc-800">
            <th
              scope="col"
              className="text-left pb-2 pr-4 text-xs font-medium text-zinc-500 uppercase tracking-wider"
            >
              Date
            </th>
            <th
              scope="col"
              className="text-left pb-2 pr-4 text-xs font-medium text-zinc-500 uppercase tracking-wider"
            >
              Side
            </th>
            <th
              scope="col"
              className="text-right pb-2 pr-4 text-xs font-medium text-zinc-500 uppercase tracking-wider"
            >
              Price
            </th>
            <th
              scope="col"
              className="text-right pb-2 pr-4 text-xs font-medium text-zinc-500 uppercase tracking-wider"
            >
              Quantity
            </th>
            <th
              scope="col"
              className="text-right pb-2 pr-4 text-xs font-medium text-zinc-500 uppercase tracking-wider"
            >
              Equity After
            </th>
            <th
              scope="col"
              className="text-left pb-2 text-xs font-medium text-zinc-500 uppercase tracking-wider"
            >
              Reason
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-800/40">
          {trades.map((trade, idx) => (
            <tr key={idx} className="hover:bg-zinc-900/50 transition-colors">
              <td className="py-2.5 pr-4 font-mono text-xs text-zinc-400">
                {formatDate(trade.timestamp)}
              </td>
              <td className="py-2.5 pr-4">
                <span
                  className={`font-mono text-xs font-semibold uppercase ${
                    trade.side.toLowerCase() === 'buy'
                      ? 'text-emerald-400'
                      : 'text-rose-400'
                  }`}
                >
                  {trade.side}
                </span>
              </td>
              <td className="py-2.5 pr-4 text-right font-mono text-xs text-zinc-200">
                {formatCurrency(trade.price)}
              </td>
              <td className="py-2.5 pr-4 text-right font-mono text-xs text-zinc-200">
                {trade.quantity.toFixed(4)}
              </td>
              <td className="py-2.5 pr-4 text-right font-mono text-xs text-zinc-200">
                {formatCurrency(trade.equity_after)}
              </td>
              <td className="py-2.5 text-xs text-zinc-400 max-w-xs">
                <span title={trade.reason} className="block truncate">
                  {trade.reason}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
