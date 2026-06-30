import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { listRuns, runBacktest } from '../api/backtests'
import { listDeployments } from '../api/paperTrading'
import { listIngestionRuns } from '../api/ingestion'
import type { RunSummary } from '../types/backtest'
import type { DeploymentSummary } from '../types/paperTrading'
import type { IngestionRunSummary } from '../types/ingestion'
import { RunStatusBadge } from '../components/RunStatusBadge'
import { PageHeader, SectionHeader, Stat, StatGrid, Table, Th, Td } from '../components/ui'
import {
  formatCurrency,
  formatPercent,
  formatSignedPercent,
  formatDate,
  returnClass,
} from '../utils/format'
import { extractMessage } from '../utils/errors'

const SAMPLE_REQUEST = {
  symbol: 'SYNTH',
  csv_path: 'data/sample/sample_ohlcv.csv',
  initial_capital: 100_000,
  fee_bps: 5,
  slippage_bps: 5,
  max_position_pct: 0.95,
} as const

interface Summary {
  runs: RunSummary[]
  deployments: DeploymentSummary[] | null
  ingestion: IngestionRunSummary[] | null
}

function SummaryStats({ runs, deployments, ingestion }: Summary) {
  const best = runs.reduce<RunSummary | null>(
    (acc, r) => (acc === null || r.total_return_pct > acc.total_return_pct ? r : acc),
    null,
  )
  const enabled = deployments?.filter((d) => d.enabled).length ?? null
  const lastIngest = ingestion?.[0] ?? null

  return (
    <StatGrid>
      <Stat
        label="Backtests"
        value={runs.length}
        hint="Saved simulated runs"
      />
      <Stat
        label="Best Return"
        value={best ? formatSignedPercent(best.total_return_pct) : '—'}
        tone={best && best.total_return_pct > 0 ? 'pos' : 'default'}
        hint={best ? `${best.symbol} · ${best.strategy_name}` : 'No runs yet'}
      />
      <Stat
        label="Active Paper"
        value={enabled === null ? '—' : enabled}
        hint={
          deployments === null
            ? 'Unavailable'
            : `of ${deployments.length} deployment${deployments.length === 1 ? '' : 's'}`
        }
      />
      <Stat
        label="Last Ingestion"
        value={lastIngest ? formatDate(lastIngest.created_at) : '—'}
        hint={
          ingestion === null
            ? 'Unavailable'
            : lastIngest
              ? `${lastIngest.provider} · ${lastIngest.symbol} · ${lastIngest.status}`
              : 'No ingest runs'
        }
      />
    </StatGrid>
  )
}

function LatestRunCard({ run }: { run: RunSummary }) {
  const retClass = returnClass(run.total_return_pct)

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded p-5">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <p className="text-xs text-zinc-500 font-mono mb-1">Run #{run.id}</p>
          <h3 className="text-base font-semibold text-zinc-50">{run.symbol}</h3>
          <p className="text-xs text-zinc-500 mt-0.5">{run.strategy_name}</p>
        </div>
        <RunStatusBadge status={run.status} />
      </div>

      <dl className="grid grid-cols-2 sm:grid-cols-3 gap-y-3 gap-x-4">
        <div>
          <dt className="text-[11px] text-zinc-500 uppercase tracking-wider">Total Return</dt>
          <dd className={`font-mono text-lg font-semibold mt-0.5 ${retClass}`}>
            {formatSignedPercent(run.total_return_pct)}
          </dd>
        </div>
        <div>
          <dt className="text-[11px] text-zinc-500 uppercase tracking-wider">Final Equity</dt>
          <dd className="font-mono text-lg font-semibold mt-0.5 text-zinc-50">
            {formatCurrency(run.final_equity)}
          </dd>
        </div>
        <div>
          <dt className="text-[11px] text-zinc-500 uppercase tracking-wider">Max Drawdown</dt>
          <dd className="font-mono text-lg font-semibold mt-0.5 text-rose-400">
            −{formatPercent(run.max_drawdown_pct)}
          </dd>
        </div>
        <div>
          <dt className="text-[11px] text-zinc-500 uppercase tracking-wider">Sharpe</dt>
          <dd className="font-mono text-lg font-semibold mt-0.5 text-zinc-50">
            {run.sharpe_ratio.toFixed(2)}
          </dd>
        </div>
        <div>
          <dt className="text-[11px] text-zinc-500 uppercase tracking-wider">Round Trips</dt>
          <dd className="font-mono text-lg font-semibold mt-0.5 text-zinc-50">
            {run.num_trades}
          </dd>
        </div>
        <div>
          <dt className="text-[11px] text-zinc-500 uppercase tracking-wider">Date</dt>
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

function RecentRunsTable({ runs }: { runs: RunSummary[] }) {
  return (
    <Table>
      <thead>
        <tr className="border-b border-zinc-800">
          <Th>ID</Th>
          <Th>Symbol</Th>
          <Th>Strategy</Th>
          <Th align="right" sub="%">Return</Th>
          <Th align="right">Sharpe</Th>
          <Th align="right" sub="trips">Trades</Th>
          <Th>Status</Th>
          <Th align="right">Date</Th>
        </tr>
      </thead>
      <tbody className="divide-y divide-zinc-800/60">
        {runs.map((run) => (
          <tr key={run.id} className="hover:bg-zinc-900/50 transition-colors">
            <Td mono className="text-zinc-500">
              <Link to={`/backtests/${run.id}`} className="hover:text-amber-400">
                #{run.id}
              </Link>
            </Td>
            <Td mono className="text-zinc-100">{run.symbol}</Td>
            <Td className="text-zinc-400">{run.strategy_name}</Td>
            <Td mono align="right" className={returnClass(run.total_return_pct)}>
              {formatSignedPercent(run.total_return_pct)}
            </Td>
            <Td mono align="right" className="text-zinc-200">
              {run.sharpe_ratio.toFixed(2)}
            </Td>
            <Td mono align="right" className="text-zinc-200">{run.num_trades}</Td>
            <Td><RunStatusBadge status={run.status} /></Td>
            <Td mono align="right" className="text-zinc-400">{formatDate(run.created_at)}</Td>
          </tr>
        ))}
      </tbody>
    </Table>
  )
}

export default function Dashboard() {
  const [data, setData] = useState<Summary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [isRunning, setIsRunning] = useState(false)
  const [runError, setRunError] = useState<string | null>(null)
  const [runSuccess, setRunSuccess] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      // Runs are required for the page; paper + ingestion are best-effort
      // context — if either endpoint is down, that stat degrades to "—".
      const [runs, deployments, ingestion] = await Promise.all([
        listRuns(),
        listDeployments().catch(() => null),
        listIngestionRuns().catch(() => null),
      ])
      setData({ runs, deployments, ingestion })
    } catch (err) {
      setError(extractMessage(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const handleRunSample = async () => {
    setIsRunning(true)
    setRunError(null)
    setRunSuccess(false)
    try {
      await runBacktest(SAMPLE_REQUEST)
      setRunSuccess(true)
      void load()
    } catch (err) {
      setRunError(extractMessage(err))
    } finally {
      setIsRunning(false)
    }
  }

  const runs = data?.runs ?? []
  const latest = runs[0] ?? null
  const recent = runs.slice(1, 6)

  return (
    <div className="space-y-8">
      <PageHeader
        title="Dashboard"
        subtitle="A simulated trading research terminal. Run rule-based strategies over historical data, measure them net of fees and slippage, and forward-test on paper. Historical data only — not financial advice."
      />

      {/* Cross-surface summary */}
      <section aria-labelledby="summary-heading">
        <SectionHeader
          id="summary-heading"
          title="At a Glance"
          subtitle="Live counts across backtests, paper deployments, and data ingestion."
        />
        {loading ? (
          <StatGrid>
            {[0, 1, 2, 3].map((n) => (
              <div
                key={n}
                className="bg-zinc-900 border border-zinc-800 rounded p-4 h-[88px] motion-safe:animate-pulse"
                aria-busy="true"
              />
            ))}
          </StatGrid>
        ) : error !== null ? (
          <div className="bg-zinc-900 border border-zinc-800 rounded p-5">
            <p role="alert" className="text-sm text-rose-400">{error}</p>
            <button
              type="button"
              onClick={() => void load()}
              className="mt-3 text-sm text-amber-400 hover:text-amber-300 transition-colors"
            >
              Retry
            </button>
          </div>
        ) : data !== null ? (
          <SummaryStats {...data} />
        ) : null}
      </section>

      {/* Run sample */}
      <section aria-labelledby="run-heading">
        <SectionHeader
          id="run-heading"
          title="Quick Action"
          subtitle="Run the bundled synthetic dataset through the trend-following strategy — no setup required."
        />
        <div className="bg-zinc-900 border border-zinc-800 rounded p-5">
          <p className="text-sm text-zinc-400 mb-4">
            Initial capital{' '}
            <span className="font-mono text-zinc-300">$100,000</span> · Fee{' '}
            <span className="font-mono text-zinc-300">5 bps</span> · Slippage{' '}
            <span className="font-mono text-zinc-300">5 bps</span> · Max position{' '}
            <span className="font-mono text-zinc-300">95%</span>.
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
            <p role="alert" className="mt-3 text-sm text-rose-400">{runError}</p>
          )}
        </div>
      </section>

      {/* Latest run */}
      <section aria-labelledby="latest-heading">
        <SectionHeader
          id="latest-heading"
          title="Latest Run"
          subtitle="The most recent backtest, with its headline performance."
        />
        {loading ? (
          <div
            className="bg-zinc-900 border border-zinc-800 rounded p-5 h-48 motion-safe:animate-pulse"
            aria-busy="true"
            aria-label="Loading latest run"
          />
        ) : error !== null ? null : latest === null ? (
          <div className="bg-zinc-900 border border-zinc-800 rounded p-8 text-center">
            <p className="text-sm text-zinc-500">
              No backtests yet. Run the sample above to get started.
            </p>
          </div>
        ) : (
          <LatestRunCard run={latest} />
        )}
      </section>

      {/* Recent runs */}
      {recent.length > 0 && (
        <section aria-labelledby="recent-heading">
          <SectionHeader
            id="recent-heading"
            title="Recent Runs"
            subtitle="Earlier backtests, newest first."
            right={
              <Link
                to="/backtests"
                className="text-xs text-amber-400 hover:text-amber-300 transition-colors"
              >
                All backtests →
              </Link>
            }
          />
          <div className="bg-zinc-900 border border-zinc-800 rounded px-4 py-3">
            <RecentRunsTable runs={recent} />
          </div>
        </section>
      )}
    </div>
  )
}
