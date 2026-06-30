import type { Trade } from '../types/backtest'
import { formatCurrency, formatDate } from '../utils/format'
import { Table, Th, Td } from './ui'

interface TradeTableProps {
  trades: Trade[]
}

export function TradeTable({ trades }: TradeTableProps) {
  if (trades.length === 0) {
    return (
      <div className="flex items-center justify-center py-12 text-ink-subtle text-sm">
        No trades recorded for this backtest.
      </div>
    )
  }

  const totalFees = trades.reduce((sum, t) => sum + t.fee, 0)
  const totalSlippage = trades.reduce((sum, t) => sum + t.slippage, 0)

  return (
    <Table maxHeight="28rem">
      <thead>
        <tr className="border-b border-hairline">
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
      <tbody className="divide-y divide-hairline/60">
        {trades.map((trade, idx) => (
          <tr key={idx} className="hover:bg-raised/50 transition-colors">
            <Td mono className="text-ink-muted">{formatDate(trade.timestamp)}</Td>
            <Td>
              <span
                className={`font-mono text-xs font-semibold uppercase ${
                  trade.side.toLowerCase() === 'buy' ? 'text-positive' : 'text-negative'
                }`}
              >
                {trade.side}
              </span>
            </Td>
            <Td mono align="right" className="text-ink">{formatCurrency(trade.price)}</Td>
            <Td mono align="right" className="text-ink">{trade.quantity.toFixed(4)}</Td>
            <Td mono align="right" className="text-ink-muted">{formatCurrency(trade.fee)}</Td>
            <Td mono align="right" className="text-ink-muted">{formatCurrency(trade.slippage)}</Td>
            <Td mono align="right" className="text-ink">{formatCurrency(trade.equity_after)}</Td>
            <Td className="text-xs text-ink-muted max-w-xs">
              <span title={trade.reason} className="block truncate">{trade.reason}</span>
            </Td>
          </tr>
        ))}
      </tbody>
      <tfoot>
        <tr className="border-t border-edge">
          <Td colSpan={4} className="text-[11px] uppercase tracking-wider text-ink-subtle">
            Totals · {trades.length} fills
          </Td>
          <Td mono align="right" className="text-ink font-medium">{formatCurrency(totalFees)}</Td>
          <Td mono align="right" className="text-ink font-medium">{formatCurrency(totalSlippage)}</Td>
          <Td colSpan={2}>{''}</Td>
        </tr>
      </tfoot>
    </Table>
  )
}
