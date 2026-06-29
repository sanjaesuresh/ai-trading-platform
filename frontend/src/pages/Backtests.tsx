import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { listRuns } from '../api/backtests'
import type { RunSummary } from '../types/backtest'
import { RunStatusBadge } from '../components/RunStatusBadge'
import { formatCurrency, formatPercent, formatDate, returnClass } from '../utils/format'
import { extractMessage } from '../utils/errors'

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

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-zinc-50">Saved Backtests</h1>
        <p className="text-sm text-zinc-500 mt-1">
          All simulated runs, newest first. For research purposes only.
        </p>
      </div>

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
          <p role="alert" className="text-sm text-rose-400">
            {error}
          </p>
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
          <Link
            to="/"
            className="text-sm text-amber-400 hover:text-amber-300 transition-colors"
          >
            Go to Dashboard →
          </Link>
        </div>
      ) : (
        <div className="bg-zinc-900 border border-zinc-800 rounded overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-800 bg-zinc-950/60">
                  <th
                    scope="col"
                    className="text-left px-4 py-3 text-xs font-medium text-zinc-500 uppercase tracking-wider"
                  >
                    ID
                  </th>
                  <th
                    scope="col"
                    className="text-left px-4 py-3 text-xs font-medium text-zinc-500 uppercase tracking-wider"
                  >
                    Symbol
                  </th>
                  <th
                    scope="col"
                    className="text-left px-4 py-3 text-xs font-medium text-zinc-500 uppercase tracking-wider"
                  >
                    Strategy
                  </th>
                  <th
                    scope="col"
                    className="text-right px-4 py-3 text-xs font-medium text-zinc-500 uppercase tracking-wider"
                  >
                    Final Equity
                  </th>
                  <th
                    scope="col"
                    className="text-right px-4 py-3 text-xs font-medium text-zinc-500 uppercase tracking-wider"
                  >
                    Return
                  </th>
                  <th
                    scope="col"
                    className="text-right px-4 py-3 text-xs font-medium text-zinc-500 uppercase tracking-wider"
                  >
                    Drawdown
                  </th>
                  <th
                    scope="col"
                    className="text-right px-4 py-3 text-xs font-medium text-zinc-500 uppercase tracking-wider"
                  >
                    Sharpe
                  </th>
                  <th
                    scope="col"
                    className="text-right px-4 py-3 text-xs font-medium text-zinc-500 uppercase tracking-wider"
                  >
                    Round Trips
                  </th>
                  <th
                    scope="col"
                    className="text-left px-4 py-3 text-xs font-medium text-zinc-500 uppercase tracking-wider"
                  >
                    Status
                  </th>
                  <th
                    scope="col"
                    className="text-left px-4 py-3 text-xs font-medium text-zinc-500 uppercase tracking-wider"
                  >
                    Date
                  </th>
                  <th scope="col" className="px-4 py-3">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800/50">
                {runs.map((run) => {
                  const retClass = returnClass(run.total_return_pct)
                  const prefix = run.total_return_pct > 0 ? '+' : ''
                  return (
                    <tr key={run.id} className="hover:bg-zinc-800/30 transition-colors">
                      <td className="px-4 py-3 font-mono text-xs text-zinc-500">
                        #{run.id}
                      </td>
                      <td className="px-4 py-3 font-mono font-medium text-zinc-50 text-xs">
                        {run.symbol}
                      </td>
                      <td className="px-4 py-3 text-zinc-400 text-xs">
                        {run.strategy_name}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-xs text-zinc-200">
                        {formatCurrency(run.final_equity)}
                      </td>
                      <td className={`px-4 py-3 text-right font-mono text-xs font-medium ${retClass}`}>
                        {prefix}{formatPercent(run.total_return_pct)}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-xs text-rose-400">
                        −{formatPercent(run.max_drawdown_pct)}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-xs text-zinc-200">
                        {run.sharpe_ratio.toFixed(2)}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-xs text-zinc-200">
                        {run.num_trades}
                      </td>
                      <td className="px-4 py-3">
                        <RunStatusBadge status={run.status} />
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-zinc-500">
                        {formatDate(run.created_at)}
                      </td>
                      <td className="px-4 py-3">
                        <Link
                          to={`/backtests/${run.id}`}
                          className="text-xs text-amber-400 hover:text-amber-300 transition-colors whitespace-nowrap"
                        >
                          Detail →
                        </Link>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
