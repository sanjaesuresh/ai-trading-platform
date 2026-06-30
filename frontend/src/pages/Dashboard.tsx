import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { listRuns, runBacktest } from '../api/backtests'
import { listDeployments } from '../api/paperTrading'
import { listIngestionRuns } from '../api/ingestion'
import type { RunSummary } from '../types/backtest'
import type { DeploymentSummary } from '../types/paperTrading'
import type { IngestionRunSummary } from '../types/ingestion'
import { RunStatusBadge } from '../components/RunStatusBadge'
import {
  PageIntro,
  SectionHeader,
  Stat,
  StatGrid,
  Table,
  Th,
  Td,
  Term,
} from '../components/ui'
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

// The four-step mental model of the whole platform, shown to first-time
// visitors so they know where each tab fits before clicking anything.
const STEPS: { n: number; icon: string; title: string; body: string; to: string; cta: string }[] = [
  {
    n: 1,
    icon: '📥',
    title: 'Get price data',
    body: 'Pull in historical prices for the symbols you want to study.',
    to: '/ingestion',
    cta: 'Data',
  },
  {
    n: 2,
    icon: '🧪',
    title: 'Test a strategy',
    body: 'Replay a set of buy/sell rules over that history — fees and slippage included.',
    to: '/new',
    cta: 'New Run',
  },
  {
    n: 3,
    icon: '📊',
    title: 'Read honest results',
    body: 'See the returns, the risk, and whether it actually beat a simple baseline.',
    to: '/backtests',
    cta: 'Backtests',
  },
  {
    n: 4,
    icon: '📈',
    title: 'Paper-trade it',
    body: 'Take one that looked strong in the backtest and run it forward on a practice account. Still fake money.',
    to: '/paper',
    cta: 'Paper',
  },
]

function HowItWorks() {
  return (
    <section aria-labelledby="how-heading">
      <SectionHeader
        id="how-heading"
        title="How this works"
        subtitle="Four steps, four tabs. Each card links to where you do that step."
      />
      <ol role="list" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 list-none p-0 m-0">
        {STEPS.map((step) => (
          <li key={step.n}>
            <Link
              to={step.to}
              className="group flex h-full flex-col rounded-lg border border-hairline bg-surface p-4 shadow-card transition-colors hover:border-accent/50"
            >
              <div className="flex items-center gap-2.5 mb-2">
                <span
                  aria-hidden
                  className="grid h-8 w-8 place-items-center rounded-lg bg-accent/10 border border-accent/30 text-base"
                >
                  {step.icon}
                </span>
                <span className="text-[11px] font-semibold uppercase tracking-widest text-accent">
                  Step {step.n}
                </span>
              </div>
              <h3 className="text-sm font-semibold text-ink">{step.title}</h3>
              <p className="mt-1 text-xs leading-relaxed text-ink-muted flex-1">
                {step.body}
              </p>
              <span className="mt-3 text-xs font-medium text-accent group-hover:text-accent-bright transition-colors">
                {step.cta} →
              </span>
            </Link>
          </li>
        ))}
      </ol>
    </section>
  )
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
      <Stat label="Backtests" value={runs.length} hint="Saved simulated runs" />
      <Stat
        label="Best Return"
        value={best ? formatSignedPercent(best.total_return_pct) : '—'}
        tone={best && best.total_return_pct > 0 ? 'pos' : 'default'}
        hint={best ? `${best.symbol} · ${best.strategy_name} · simulated` : 'No runs yet'}
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
        label="Last Data Pull"
        value={lastIngest ? formatDate(lastIngest.created_at) : '—'}
        hint={
          ingestion === null
            ? 'Unavailable'
            : lastIngest
              ? `${lastIngest.provider} · ${lastIngest.symbol} · ${lastIngest.status}`
              : 'No data pulls yet'
        }
      />
    </StatGrid>
  )
}

function LatestRunCard({ run }: { run: RunSummary }) {
  const retClass = returnClass(run.total_return_pct)

  return (
    <div className="bg-surface border border-hairline rounded-lg p-5 shadow-card">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <p className="text-xs text-ink-subtle font-mono mb-1">Run #{run.id}</p>
          <h3 className="text-base font-semibold text-ink">{run.symbol}</h3>
          <p className="text-xs text-ink-muted mt-0.5">{run.strategy_name}</p>
        </div>
        <RunStatusBadge status={run.status} />
      </div>

      <dl className="grid grid-cols-2 sm:grid-cols-3 gap-y-3 gap-x-4">
        <div>
          <dt className="text-[11px] text-ink-subtle uppercase tracking-wider">
            Total Return <Term id="total_return" withLabel={false} />
          </dt>
          <dd className={`font-mono text-lg font-semibold mt-0.5 ${retClass}`}>
            {formatSignedPercent(run.total_return_pct)}
          </dd>
        </div>
        <div>
          <dt className="text-[11px] text-ink-subtle uppercase tracking-wider">Final Equity</dt>
          <dd className="font-mono text-lg font-semibold mt-0.5 text-ink">
            {formatCurrency(run.final_equity)}
          </dd>
        </div>
        <div>
          <dt className="text-[11px] text-ink-subtle uppercase tracking-wider">
            Max Drawdown <Term id="max_drawdown" withLabel={false} />
          </dt>
          <dd className="font-mono text-lg font-semibold mt-0.5 text-negative">
            −{formatPercent(run.max_drawdown_pct)}
          </dd>
        </div>
        <div>
          <dt className="text-[11px] text-ink-subtle uppercase tracking-wider">
            Sharpe <Term id="sharpe_ratio" withLabel={false} />
          </dt>
          <dd className="font-mono text-lg font-semibold mt-0.5 text-ink">
            {run.sharpe_ratio.toFixed(2)}
          </dd>
        </div>
        <div>
          <dt className="text-[11px] text-ink-subtle uppercase tracking-wider">Round Trips</dt>
          <dd className="font-mono text-lg font-semibold mt-0.5 text-ink">
            {run.num_trades}
          </dd>
        </div>
        <div>
          <dt className="text-[11px] text-ink-subtle uppercase tracking-wider">Date</dt>
          <dd className="font-mono text-sm font-medium mt-0.5 text-ink-muted">
            {formatDate(run.created_at)}
          </dd>
        </div>
      </dl>

      <div className="mt-4 pt-4 border-t border-hairline">
        <Link
          to={`/backtests/${run.id}`}
          className="text-sm text-accent hover:text-accent-bright transition-colors font-medium"
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
        <tr className="border-b border-hairline">
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
      <tbody className="divide-y divide-hairline/70">
        {runs.map((run) => (
          <tr key={run.id} className="hover:bg-raised/50 transition-colors">
            <Td mono className="text-ink-subtle">
              <Link to={`/backtests/${run.id}`} className="hover:text-accent">
                #{run.id}
              </Link>
            </Td>
            <Td mono className="text-ink">{run.symbol}</Td>
            <Td className="text-ink-muted">{run.strategy_name}</Td>
            <Td mono align="right" className={returnClass(run.total_return_pct)}>
              {formatSignedPercent(run.total_return_pct)}
            </Td>
            <Td mono align="right" className="text-ink">
              {run.sharpe_ratio.toFixed(2)}
            </Td>
            <Td mono align="right" className="text-ink">{run.num_trades}</Td>
            <Td><RunStatusBadge status={run.status} /></Td>
            <Td mono align="right" className="text-ink-muted">{formatDate(run.created_at)}</Td>
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
    <div className="space-y-10">
      <PageIntro title="Welcome to AI Trading Lab" icon="🔬" eyebrow="Home">
        A sandbox for testing trading ideas <strong className="text-ink">without
        risking real money</strong>. You write down a set of buy/sell rules, replay
        them over real historical prices to see how they would have done, and then —
        if one looks promising — watch it run forward on a practice account.
        Everything you see is a <Term id="backtest">simulation</Term>; none of it is
        financial advice.
      </PageIntro>

      <HowItWorks />

      {/* Cross-surface summary */}
      <section aria-labelledby="summary-heading">
        <SectionHeader
          id="summary-heading"
          title="At a glance"
          subtitle="A quick count of what you've done so far across the whole platform."
        />
        {loading ? (
          <StatGrid>
            {[0, 1, 2, 3].map((n) => (
              <div
                key={n}
                className="bg-surface border border-hairline rounded-lg p-4 h-[88px] motion-safe:animate-pulse"
                aria-busy="true"
              />
            ))}
          </StatGrid>
        ) : error !== null ? (
          <div className="bg-surface border border-hairline rounded-lg p-5">
            <p role="alert" className="text-sm text-negative">{error}</p>
            <button
              type="button"
              onClick={() => void load()}
              className="mt-3 text-sm text-accent hover:text-accent-bright transition-colors"
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
          title="Try it in one click"
          subtitle="New here? Run the bundled practice dataset through a simple trend-following strategy — no setup needed."
        />
        <div className="bg-surface border border-hairline rounded-lg p-5 shadow-card">
          <p className="text-sm text-ink-muted mb-4">
            Starts with{' '}
            <span className="font-mono text-ink">$100,000</span> of pretend cash ·{' '}
            <Term id="fees">Fee</Term>{' '}
            <span className="font-mono text-ink">5 bps</span> ·{' '}
            <Term id="slippage">Slippage</Term>{' '}
            <span className="font-mono text-ink">5 bps</span> · up to{' '}
            <span className="font-mono text-ink">95%</span> in one position.
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => void handleRunSample()}
              disabled={isRunning}
              aria-busy={isRunning}
              className="inline-flex items-center gap-2 px-4 py-2 bg-accent text-canvas text-sm font-semibold rounded-lg transition-colors hover:bg-accent-bright disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isRunning ? (
                <>
                  <span
                    className="inline-block h-3 w-3 border-2 border-canvas/30 border-t-canvas rounded-full motion-safe:animate-spin"
                    aria-hidden="true"
                  />
                  Running…
                </>
              ) : (
                'Run sample backtest'
              )}
            </button>
            <Link
              to="/new"
              className="inline-flex items-center px-4 py-2 border border-edge text-ink text-sm font-medium rounded-lg transition-colors hover:border-accent"
            >
              Configure my own →
            </Link>
            {runSuccess && (
              <p role="status" className="text-sm text-positive">
                Done — your new run is below.
              </p>
            )}
          </div>
          {runError !== null && (
            <p role="alert" className="mt-3 text-sm text-negative">{runError}</p>
          )}
        </div>
      </section>

      {/* Latest run */}
      <section aria-labelledby="latest-heading">
        <SectionHeader
          id="latest-heading"
          title="Your latest run"
          subtitle="The most recent backtest and how it turned out."
        />
        {loading ? (
          <div
            className="bg-surface border border-hairline rounded-lg p-5 h-48 motion-safe:animate-pulse"
            aria-busy="true"
            aria-label="Loading latest run"
          />
        ) : error !== null ? null : latest === null ? (
          <div className="bg-surface border border-hairline rounded-lg p-8 text-center">
            <p className="text-sm text-ink-muted">
              No backtests yet. Run the sample above to see what results look like.
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
            title="Earlier runs"
            subtitle="Your backtest history, newest first."
            right={
              <Link
                to="/backtests"
                className="text-xs text-accent hover:text-accent-bright transition-colors"
              >
                All backtests →
              </Link>
            }
          />
          <div className="bg-surface border border-hairline rounded-lg px-4 py-3 shadow-card">
            <RecentRunsTable runs={recent} />
          </div>
        </section>
      )}
    </div>
  )
}
