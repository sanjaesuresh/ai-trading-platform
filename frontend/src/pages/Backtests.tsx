import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { listRuns } from '../api/backtests'
import type { RunSummary } from '../types/backtest'
import { RunStatusBadge } from '../components/RunStatusBadge'
import { PageHeader, Table, Th, Td } from '../components/ui'
import {
  formatCurrency,
  formatPercent,
  formatSignedPercent,
  formatDate,
  returnClass,
} from '../utils/format'
import { extractMessage } from '../utils/errors'

function mean(values: number[]): number {
  if (values.length === 0) return 0
  return values.reduce((s, v) => s + v, 0) / values.length
}

export default function Backtests() {
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const loadRuns = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await listRuns()
      setRuns(data)
    } catch (err) {
      setError(extractMessage(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadRuns()
  }, [loadRuns])

  const avgReturn = mean(runs.map((r) => r.total_return_pct))
  const avgSharpe = mean(runs.map((r) => r.sharpe_ratio))

  return (
    <div className="space-y-6">
      <PageHeader
        title="Saved Backtests"
        subtitle="Every simulated run, newest first. Returns are net of the fees and slippage each run was configured with. For research purposes only."
        meta={
          runs.length > 0 ? (
            <span className="font-mono text-sm text-zinc-500">
              {runs.length} run{runs.length === 1 ? '' : 's'}
            </span>
          ) : undefined
        }
      />

      {loading ? (
        <div
          className="bg-zinc-900 border border-zinc-800 rounded overflow-hidden motion-safe:animate-pulse"
          aria-busy="true"
          aria-label="Loading backtests"
        >
          {[1, 2, 3].map((n) => (
            <div key={n} className="p-4 border-b border-zinc-800 last:border-b-0">
              <div className="h-3 bg-zinc-800 rounded w-32 mb-2" />
              <div className="h-2 bg-zinc-800 rounded w-24" />
            </div>
          ))}
        </div>
      ) : error !== null ? (
        <div className="bg-zinc-900 border border-zinc-800 rounded p-5">
          <p role="alert" className="text-sm text-rose-400">{error}</p>
          <button
            type="button"
            onClick={() => void loadRuns()}
            className="mt-3 text-sm text-amber-400 hover:text-amber-300 transition-colors"
          >
            Retry
          </button>
        </div>
      ) : runs.length === 0 ? (
        <div className="bg-zinc-900 border border-zinc-800 rounded p-8 text-center">
          <p className="text-sm text-zinc-500 mb-3">
            No backtests found. Run the sample on the Dashboard to get started.
          </p>
          <Link to="/" className="text-sm text-amber-400 hover:text-amber-300 transition-colors">
            Go to Dashboard →
          </Link>
        </div>
      ) : (
        <div className="bg-zinc-900 border border-zinc-800 rounded px-4 py-3">
          <Table>
            <thead>
              <tr className="border-b border-zinc-800">
                <Th>ID</Th>
                <Th>Symbol</Th>
                <Th>Strategy</Th>
                <Th align="right" sub="USD">Final Equity</Th>
                <Th align="right" sub="%">Return</Th>
                <Th align="right" sub="%">Drawdown</Th>
                <Th align="right">Sharpe</Th>
                <Th align="right" sub="trips">Trades</Th>
                <Th>Status</Th>
                <Th align="right">Date</Th>
                <Th align="right"><span className="sr-only">Actions</span></Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800/50">
              {runs.map((run) => (
                <tr key={run.id} className="hover:bg-zinc-800/30 transition-colors">
                  <Td mono className="text-zinc-500">#{run.id}</Td>
                  <Td mono className="font-medium text-zinc-50">{run.symbol}</Td>
                  <Td className="text-zinc-400 text-xs">{run.strategy_name}</Td>
                  <Td mono align="right" className="text-zinc-200">{formatCurrency(run.final_equity)}</Td>
                  <Td mono align="right" className={`font-medium ${returnClass(run.total_return_pct)}`}>
                    {formatSignedPercent(run.total_return_pct)}
                  </Td>
                  <Td mono align="right" className="text-rose-400">−{formatPercent(run.max_drawdown_pct)}</Td>
                  <Td mono align="right" className="text-zinc-200">{run.sharpe_ratio.toFixed(2)}</Td>
                  <Td mono align="right" className="text-zinc-200">{run.num_trades}</Td>
                  <Td><RunStatusBadge status={run.status} /></Td>
                  <Td mono align="right" className="text-zinc-500">{formatDate(run.created_at)}</Td>
                  <Td align="right">
                    <Link
                      to={`/backtests/${run.id}`}
                      className="text-xs text-amber-400 hover:text-amber-300 transition-colors whitespace-nowrap"
                    >
                      Detail →
                    </Link>
                  </Td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t border-zinc-700">
                <Td colSpan={4} className="text-[11px] uppercase tracking-wider text-zinc-500">
                  Average across {runs.length} run{runs.length === 1 ? '' : 's'}
                </Td>
                <Td mono align="right" className={`font-medium ${returnClass(avgReturn)}`}>
                  {formatSignedPercent(avgReturn)}
                </Td>
                <Td>{''}</Td>
                <Td mono align="right" className="text-zinc-200 font-medium">{avgSharpe.toFixed(2)}</Td>
                <Td colSpan={4}>{''}</Td>
              </tr>
            </tfoot>
          </Table>
        </div>
      )}
    </div>
  )
}
