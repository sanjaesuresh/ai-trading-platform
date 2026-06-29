import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { getRun } from '../api/backtests'
import type { RunDetail } from '../types/backtest'
import { MetricsCards } from '../components/MetricsCards'
import { EquityCurve } from '../components/EquityCurve'
import { TradeTable } from '../components/TradeTable'
import { RunStatusBadge } from '../components/RunStatusBadge'
import {
  formatCurrency,
  formatPercent,
  formatFraction,
  formatDate,
  returnClass,
} from '../utils/format'
import { extractMessage, isNotFound } from '../utils/errors'

function renderConfigValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function SectionHeading({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <h2
      id={id}
      className="text-xs font-medium text-zinc-500 uppercase tracking-wider mb-3"
    >
      {children}
    </h2>
  )
}

function DetailSkeleton() {
  return (
    <div className="space-y-6 motion-safe:animate-pulse" aria-busy="true" aria-label="Loading">
      <div className="h-6 bg-zinc-800 rounded w-48" />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[1, 2, 3, 4, 5, 6, 7].map((n) => (
          <div key={n} className="bg-zinc-900 border border-zinc-800 rounded p-4">
            <div className="h-2 bg-zinc-800 rounded w-16 mb-3" />
            <div className="h-6 bg-zinc-800 rounded w-20" />
          </div>
        ))}
      </div>
      <div className="bg-zinc-900 border border-zinc-800 rounded p-4 h-64" />
    </div>
  )
}

export default function BacktestDetail() {
  const { id } = useParams<{ id: string }>()
  const [run, setRun] = useState<RunDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notFound, setNotFound] = useState(false)

  useEffect(() => {
    if (id === undefined) {
      setError('Missing backtest ID.')
      setLoading(false)
      return
    }
    const numId = parseInt(id, 10)
    if (isNaN(numId)) {
      setError('Invalid backtest ID.')
      setLoading(false)
      return
    }

    let cancelled = false
    setLoading(true)
    setError(null)
    setNotFound(false)

    getRun(numId)
      .then((data) => {
        if (!cancelled) setRun(data)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        if (isNotFound(err)) {
          setNotFound(true)
        } else {
          setError(extractMessage(err))
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [id])

  if (loading) return <DetailSkeleton />

  if (notFound) {
    return (
      <div className="bg-zinc-900 border border-zinc-800 rounded p-8 text-center">
        <p className="text-sm text-zinc-400 mb-3">Backtest #{id ?? ''} not found.</p>
        <Link to="/backtests" className="text-sm text-amber-400 hover:text-amber-300 transition-colors">
          ← Back to Backtests
        </Link>
      </div>
    )
  }

  if (error !== null) {
    return (
      <div className="bg-zinc-900 border border-zinc-800 rounded p-5">
        <p role="alert" className="text-sm text-rose-400 mb-3">
          {error}
        </p>
        <Link to="/backtests" className="text-sm text-amber-400 hover:text-amber-300 transition-colors">
          ← Back to Backtests
        </Link>
      </div>
    )
  }

  if (run === null) return null

  const retClass = returnClass(run.total_return_pct)
  const prefix = run.total_return_pct > 0 ? '+' : ''

  return (
    <div className="space-y-8">
      {/* Back link */}
      <div>
        <Link
          to="/backtests"
          className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
        >
          ← Backtests
        </Link>
      </div>

      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <h1 className="text-xl font-semibold text-zinc-50 font-mono">
              {run.symbol}
            </h1>
            <RunStatusBadge status={run.status} />
          </div>
          <p className="text-sm text-zinc-500">{run.strategy_name}</p>
          <p className="text-xs text-zinc-600 mt-1">
            Run #{run.id} · {formatDate(run.created_at)} ·
            Initial capital {formatCurrency(run.initial_capital)}
          </p>
        </div>
        <div className="text-right">
          <p className={`font-mono text-2xl font-bold ${retClass}`}>
            {prefix}{formatPercent(run.total_return_pct)}
          </p>
          <p className="text-xs text-zinc-500 mt-0.5">total return (simulated)</p>
        </div>
      </div>

      {/* Primary metrics */}
      <section aria-labelledby="metrics-heading">
        <SectionHeading id="metrics-heading">Key Metrics</SectionHeading>
        <MetricsCards run={run} />
      </section>

      {/* Extended metrics */}
      <section aria-labelledby="ext-metrics-heading">
        <SectionHeading id="ext-metrics-heading">Extended Metrics</SectionHeading>
        <div className="bg-zinc-900 border border-zinc-800 rounded p-4">
          <dl className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div>
              <dt className="text-xs text-zinc-500 uppercase tracking-wider">Annualized Return</dt>
              <dd className={`font-mono text-sm font-semibold mt-1 ${returnClass(run.metrics.annualized_return_pct)}`}>
                {run.metrics.annualized_return_pct > 0 ? '+' : ''}
                {formatPercent(run.metrics.annualized_return_pct)}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-zinc-500 uppercase tracking-wider">Sortino</dt>
              <dd className="font-mono text-sm font-semibold mt-1 text-zinc-50">
                {run.metrics.sortino_ratio.toFixed(2)}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-zinc-500 uppercase tracking-wider">Avg Win</dt>
              <dd className="font-mono text-sm font-semibold mt-1 text-emerald-400">
                {formatCurrency(run.metrics.avg_win)}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-zinc-500 uppercase tracking-wider">Avg Loss</dt>
              <dd className="font-mono text-sm font-semibold mt-1 text-rose-400">
                {formatCurrency(run.metrics.avg_loss)}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-zinc-500 uppercase tracking-wider">Avg Holding</dt>
              <dd className="font-mono text-sm font-semibold mt-1 text-zinc-50">
                {run.metrics.avg_holding_days.toFixed(1)} days
              </dd>
            </div>
            <div>
              <dt className="text-xs text-zinc-500 uppercase tracking-wider">Exposure</dt>
              <dd className="font-mono text-sm font-semibold mt-1 text-zinc-50">
                {formatFraction(run.metrics.exposure_pct)}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-zinc-500 uppercase tracking-wider">Round Trips</dt>
              <dd className="font-mono text-sm font-semibold mt-1 text-zinc-50">
                {run.metrics.num_round_trips}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-zinc-500 uppercase tracking-wider">Total Fills</dt>
              <dd className="font-mono text-sm font-semibold mt-1 text-zinc-50">
                {run.metrics.num_fills}
              </dd>
            </div>
          </dl>
        </div>
      </section>

      {/* Equity curve */}
      <section aria-labelledby="curve-heading">
        <SectionHeading id="curve-heading">Equity Curve</SectionHeading>
        <div className="bg-zinc-900 border border-zinc-800 rounded p-4">
          <EquityCurve data={run.equity_curve} />
        </div>
      </section>

      {/* Trades */}
      <section aria-labelledby="trades-heading">
        <SectionHeading id="trades-heading">
          Trades ({run.trades.length})
        </SectionHeading>
        <div className="bg-zinc-900 border border-zinc-800 rounded p-4">
          <TradeTable trades={run.trades} />
        </div>
      </section>

      {/* Config */}
      {Object.keys(run.config).length > 0 && (
        <section aria-labelledby="config-heading">
          <SectionHeading id="config-heading">Strategy Configuration</SectionHeading>
          <div className="bg-zinc-900 border border-zinc-800 rounded p-4">
            <dl className="grid grid-cols-2 sm:grid-cols-3 gap-y-3 gap-x-6">
              {Object.entries(run.config).map(([key, value]) => (
                <div key={key}>
                  <dt className="text-xs text-zinc-500 uppercase tracking-wider">
                    {key}
                  </dt>
                  <dd className="font-mono text-sm text-zinc-200 mt-0.5">
                    {renderConfigValue(value)}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        </section>
      )}
    </div>
  )
}
