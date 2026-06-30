import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { listRuns } from '../api/backtests'
import type { RunSummary } from '../types/backtest'
import { RunStatusBadge } from '../components/RunStatusBadge'
import { PageIntro, Table, Th, Td, Term } from '../components/ui'
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
      <PageIntro
        title="Saved backtests"
        icon="📊"
        eyebrow="Backtests"
        meta={
          runs.length > 0 ? (
            <span className="font-mono text-sm text-ink-subtle">
              {runs.length} run{runs.length === 1 ? '' : 's'}
            </span>
          ) : undefined
        }
      >
        Every simulated run you&apos;ve done, newest first. The returns shown
        already have each run&apos;s <Term id="fees">fees</Term> and{' '}
        <Term id="slippage">slippage</Term> subtracted, so they reflect what the
        strategy would actually have kept. Click any row for the full report.
      </PageIntro>

      {loading ? (
        <div
          className="bg-surface border border-hairline rounded-lg overflow-hidden motion-safe:animate-pulse"
          aria-busy="true"
          aria-label="Loading backtests"
        >
          {[1, 2, 3].map((n) => (
            <div key={n} className="p-4 border-b border-hairline last:border-b-0">
              <div className="h-3 bg-raised rounded w-32 mb-2" />
              <div className="h-2 bg-raised rounded w-24" />
            </div>
          ))}
        </div>
      ) : error !== null ? (
        <div className="bg-surface border border-hairline rounded-lg p-5">
          <p role="alert" className="text-sm text-negative">{error}</p>
          <button
            type="button"
            onClick={() => void loadRuns()}
            className="mt-3 text-sm text-accent hover:text-accent-bright transition-colors"
          >
            Retry
          </button>
        </div>
      ) : runs.length === 0 ? (
        <div className="bg-surface border border-hairline rounded-lg p-8 text-center">
          <p className="text-sm text-ink-muted mb-3">
            No backtests yet. Run the sample on the Home page to see what results
            look like.
          </p>
          <Link to="/" className="text-sm text-accent hover:text-accent-bright transition-colors">
            Go to Home →
          </Link>
        </div>
      ) : (
        <div className="bg-surface border border-hairline rounded-lg px-4 py-3 shadow-card">
          <Table>
            <thead>
              <tr className="border-b border-hairline">
                <Th>ID</Th>
                <Th>Symbol</Th>
                <Th>Strategy</Th>
                <Th align="right" sub="USD">Final Equity</Th>
                <Th align="right" sub="%">Return <Term id="total_return" withLabel={false} /></Th>
                <Th align="right" sub="%">Drawdown <Term id="max_drawdown" withLabel={false} /></Th>
                <Th align="right">Sharpe <Term id="sharpe_ratio" withLabel={false} /></Th>
                <Th align="right" sub="trips">Trades</Th>
                <Th>Status</Th>
                <Th align="right">Date</Th>
                <Th align="right"><span className="sr-only">Actions</span></Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-hairline/60">
              {runs.map((run) => (
                <tr key={run.id} className="hover:bg-raised/40 transition-colors">
                  <Td mono className="text-ink-subtle">#{run.id}</Td>
                  <Td mono className="font-medium text-ink">{run.symbol}</Td>
                  <Td className="text-ink-muted text-xs">{run.strategy_name}</Td>
                  <Td mono align="right" className="text-ink">{formatCurrency(run.final_equity)}</Td>
                  <Td mono align="right" className={`font-medium ${returnClass(run.total_return_pct)}`}>
                    {formatSignedPercent(run.total_return_pct)}
                  </Td>
                  <Td mono align="right" className="text-negative">−{formatPercent(run.max_drawdown_pct)}</Td>
                  <Td mono align="right" className="text-ink">{run.sharpe_ratio.toFixed(2)}</Td>
                  <Td mono align="right" className="text-ink">{run.num_trades}</Td>
                  <Td><RunStatusBadge status={run.status} /></Td>
                  <Td mono align="right" className="text-ink-subtle">{formatDate(run.created_at)}</Td>
                  <Td align="right">
                    <Link
                      to={`/backtests/${run.id}`}
                      className="text-xs text-accent hover:text-accent-bright transition-colors whitespace-nowrap"
                    >
                      Detail →
                    </Link>
                  </Td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t border-edge">
                <Td colSpan={4} className="text-[11px] uppercase tracking-wider text-ink-subtle">
                  Average across {runs.length} run{runs.length === 1 ? '' : 's'}
                </Td>
                <Td mono align="right" className={`font-medium ${returnClass(avgReturn)}`}>
                  {formatSignedPercent(avgReturn)}
                </Td>
                <Td>{''}</Td>
                <Td mono align="right" className="text-ink font-medium">{avgSharpe.toFixed(2)}</Td>
                <Td colSpan={4}>{''}</Td>
              </tr>
            </tfoot>
          </Table>
        </div>
      )}
    </div>
  )
}
