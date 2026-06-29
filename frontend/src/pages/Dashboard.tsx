import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { listRuns, runBacktest } from '../api/backtests'
import type { RunSummary } from '../types/backtest'
import { RunStatusBadge } from '../components/RunStatusBadge'
import { formatCurrency, formatPercent, formatDate, returnClass } from '../utils/format'
import { extractMessage } from '../utils/errors'

const SAMPLE_REQUEST = {
  symbol: 'SYNTH',
  csv_path: 'data/sample/sample_ohlcv.csv',
  initial_capital: 100_000,
  fee_bps: 5,
  slippage_bps: 5,
  max_position_pct: 0.95,
} as const

function LatestRunCard({ run }: { run: RunSummary }) {
  const retClass = returnClass(run.total_return_pct)
  const prefix = run.total_return_pct > 0 ? '+' : ''

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded p-5">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <p className="text-xs text-zinc-500 font-mono mb-1">Run #{run.id}</p>
          <h2 className="text-base font-semibold text-zinc-50">{run.symbol}</h2>
          <p className="text-xs text-zinc-500 mt-0.5">{run.strategy_name}</p>
        </div>
        <RunStatusBadge status={run.status} />
      </div>

      <dl className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <div>
          <dt className="text-xs text-zinc-500 uppercase tracking-wider">Total Return</dt>
          <dd className={`font-mono text-lg font-semibold mt-0.5 ${retClass}`}>
            {prefix}{formatPercent(run.total_return_pct)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-zinc-500 uppercase tracking-wider">Final Equity</dt>
          <dd className="font-mono text-lg font-semibold mt-0.5 text-zinc-50">
            {formatCurrency(run.final_equity)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-zinc-500 uppercase tracking-wider">Max Drawdown</dt>
          <dd className="font-mono text-lg font-semibold mt-0.5 text-rose-400">
            −{formatPercent(run.max_drawdown_pct)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-zinc-500 uppercase tracking-wider">Sharpe</dt>
          <dd className="font-mono text-lg font-semibold mt-0.5 text-zinc-50">
            {run.sharpe_ratio.toFixed(2)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-zinc-500 uppercase tracking-wider">Round Trips</dt>
          <dd className="font-mono text-lg font-semibold mt-0.5 text-zinc-50">
            {run.num_trades}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-zinc-500 uppercase tracking-wider">Date</dt>
          <dd className="font-mono text-sm font-medium mt-0.5 text-zinc-400">
            {formatDate(run.created_at)}
          </dd>
        </div>
      </dl>

      <div className="mt-4 pt-4 border-t border-zinc-800">
        <Link
          to={`/backtests/${run.id}`}
          className="text-sm text-amber-400 hover:text-amber-300 transition-colors font-medium"
        >
          View full detail →
        </Link>
      </div>
    </div>
  )
}

function SkeletonCard() {
  return (
    <div
      className="bg-zinc-900 border border-zinc-800 rounded p-5 motion-safe:animate-pulse"
      aria-busy="true"
      aria-label="Loading"
    >
      <div className="h-3 bg-zinc-800 rounded w-16 mb-3" />
      <div className="h-5 bg-zinc-800 rounded w-24 mb-1" />
      <div className="h-3 bg-zinc-800 rounded w-40 mb-4" />
      <div className="grid grid-cols-3 gap-3">
        {[1, 2, 3].map((n) => (
          <div key={n}>
            <div className="h-2 bg-zinc-800 rounded w-16 mb-2" />
            <div className="h-5 bg-zinc-800 rounded w-20" />
          </div>
        ))}
      </div>
    </div>
  )
}

export default function Dashboard() {
  const [latestRun, setLatestRun] = useState<RunSummary | null>(null)
  const [runsLoading, setRunsLoading] = useState(true)
  const [runsError, setRunsError] = useState<string | null>(null)
  const [isRunning, setIsRunning] = useState(false)
  const [runError, setRunError] = useState<string | null>(null)
  const [runSuccess, setRunSuccess] = useState(false)

  const loadLatest = useCallback(async () => {
    setRunsLoading(true)
    setRunsError(null)
    try {
      const runs = await listRuns()
      setLatestRun(runs[0] ?? null)
    } catch (err) {
      setRunsError(extractMessage(err))
    } finally {
      setRunsLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadLatest()
  }, [loadLatest])

  const handleRunSample = async () => {
    setIsRunning(true)
    setRunError(null)
    setRunSuccess(false)
    try {
      await runBacktest(SAMPLE_REQUEST)
      setRunSuccess(true)
      void loadLatest()
    } catch (err) {
      setRunError(extractMessage(err))
    } finally {
      setIsRunning(false)
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-xl font-semibold text-zinc-50">Dashboard</h1>
        <p className="text-sm text-zinc-500 mt-1">
          Run simulated backtests and review results. Historical data only —
          not financial advice.
        </p>
      </div>

      {/* Run sample */}
      <section aria-labelledby="run-heading">
        <h2
          id="run-heading"
          className="text-xs font-medium text-zinc-500 uppercase tracking-wider mb-3"
        >
          Quick Action
        </h2>
        <div className="bg-zinc-900 border border-zinc-800 rounded p-5">
          <p className="text-sm text-zinc-400 mb-4">
            Run the bundled synthetic OHLCV dataset through the trend-following
            strategy.{' '}
            <span className="text-zinc-500">
              Initial capital $100,000 · Fee 5 bps · Slippage 5 bps.
            </span>
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => void handleRunSample()}
              disabled={isRunning}
              aria-busy={isRunning}
              className="inline-flex items-center gap-2 px-4 py-2 bg-amber-400 text-zinc-950 text-sm font-semibold rounded transition-colors hover:bg-amber-300 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isRunning ? (
                <>
                  <span
                    className="inline-block h-3 w-3 border-2 border-zinc-950/30 border-t-zinc-950 rounded-full motion-safe:animate-spin"
                    aria-hidden="true"
                  />
                  Running…
                </>
              ) : (
                'Run Sample Backtest'
              )}
            </button>
            <Link
              to="/new"
              className="inline-flex items-center px-4 py-2 border border-zinc-700 text-zinc-200 text-sm font-medium rounded transition-colors hover:border-zinc-500"
            >
              Configure a run →
            </Link>
            {runSuccess && (
              <p role="status" className="text-sm text-emerald-400">
                Complete — latest run updated below.
              </p>
            )}
          </div>
          {runError !== null && (
            <p role="alert" className="mt-3 text-sm text-rose-400">
              {runError}
            </p>
          )}
        </div>
      </section>

      {/* Latest run */}
      <section aria-labelledby="latest-heading">
        <h2
          id="latest-heading"
          className="text-xs font-medium text-zinc-500 uppercase tracking-wider mb-3"
        >
          Latest Run
        </h2>
        {runsLoading ? (
          <SkeletonCard />
        ) : runsError !== null ? (
          <div className="bg-zinc-900 border border-zinc-800 rounded p-5">
            <p role="alert" className="text-sm text-rose-400">
              {runsError}
            </p>
            <button
              type="button"
              onClick={() => void loadLatest()}
              className="mt-3 text-sm text-amber-400 hover:text-amber-300 transition-colors"
            >
              Retry
            </button>
          </div>
        ) : latestRun === null ? (
          <div className="bg-zinc-900 border border-zinc-800 rounded p-8 text-center">
            <p className="text-sm text-zinc-500">
              No backtests yet. Run the sample above to get started.
            </p>
          </div>
        ) : (
          <LatestRunCard run={latestRun} />
        )}
      </section>
    </div>
  )
}
