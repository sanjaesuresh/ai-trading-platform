import type { Trade } from '../types/backtest'
import { formatCurrency, formatDate } from '../utils/format'
import { Table, Th, Td } from './ui'

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

  const totalFees = trades.reduce((sum, t) => sum + t.fee, 0)
  const totalSlippage = trades.reduce((sum, t) => sum + t.slippage, 0)

  return (
    <Table maxHeight="28rem">
      <thead>
        <tr className="border-b border-zinc-800">
          <Th sticky>Date</Th>
          <Th sticky>Side</Th>
          <Th sticky align="right" sub="USD">Price</Th>
          <Th sticky align="right" sub="shares">Quantity</Th>
          <Th sticky align="right" sub="USD">Fee</Th>
          <Th sticky align="right" sub="USD">Slippage</Th>
          <Th sticky align="right" sub="USD">Equity After</Th>
          <Th sticky>Reason</Th>
        </tr>
      </thead>
      <tbody className="divide-y divide-zinc-800/40">
        {trades.map((trade, idx) => (
          <tr key={idx} className="hover:bg-zinc-900/50 transition-colors">
            <Td mono className="text-zinc-400">{formatDate(trade.timestamp)}</Td>
            <Td>
              <span
                className={`font-mono text-xs font-semibold uppercase ${
                  trade.side.toLowerCase() === 'buy' ? 'text-emerald-400' : 'text-rose-400'
                }`}
              >
                {trade.side}
              </span>
            </Td>
            <Td mono align="right" className="text-zinc-200">{formatCurrency(trade.price)}</Td>
            <Td mono align="right" className="text-zinc-200">{trade.quantity.toFixed(4)}</Td>
            <Td mono align="right" className="text-zinc-400">{formatCurrency(trade.fee)}</Td>
            <Td mono align="right" className="text-zinc-400">{formatCurrency(trade.slippage)}</Td>
            <Td mono align="right" className="text-zinc-200">{formatCurrency(trade.equity_after)}</Td>
            <Td className="text-xs text-zinc-400 max-w-xs">
              <span title={trade.reason} className="block truncate">{trade.reason}</span>
            </Td>
          </tr>
        ))}
      </tbody>
      <tfoot>
        <tr className="border-t border-zinc-700">
          <Td colSpan={4} className="text-[11px] uppercase tracking-wider text-zinc-500">
            Totals · {trades.length} fills
          </Td>
          <Td mono align="right" className="text-zinc-200 font-medium">{formatCurrency(totalFees)}</Td>
          <Td mono align="right" className="text-zinc-200 font-medium">{formatCurrency(totalSlippage)}</Td>
          <Td colSpan={2}>{''}</Td>
        </tr>
      </tfoot>
    </Table>
  )
}
