import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { getRun } from '../api/backtests'
import type { RunDetail } from '../types/backtest'
import { MetricsCards } from '../components/MetricsCards'
import { EquityCurve } from '../components/EquityCurve'
import { TradeTable } from '../components/TradeTable'
import { RunStatusBadge } from '../components/RunStatusBadge'
import { SectionHeader, ProvenanceStrip } from '../components/ui'
import type { ProvenanceItem } from '../components/ui'
import {
  formatCurrency,
  formatSignedPercent,
  formatDate,
  returnClass,
} from '../utils/format'
import { extractMessage, isNotFound } from '../utils/errors'

function renderConfigValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

/** Pretty key: max_position_pct → Max Position Pct. */
function prettyKey(key: string): string {
  return key
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

function DetailSkeleton() {
  return (
    <div className="space-y-6 motion-safe:animate-pulse" aria-busy="true" aria-label="Loading">
      <div className="h-6 bg-raised rounded w-48" />
      <div className="h-10 bg-surface border border-hairline rounded" />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[1, 2, 3, 4, 5, 6, 7, 8].map((n) => (
          <div key={n} className="bg-surface border border-hairline rounded p-4">
            <div className="h-2 bg-raised rounded w-16 mb-3" />
            <div className="h-6 bg-raised rounded w-20" />
          </div>
        ))}
      </div>
      <div className="bg-surface border border-hairline rounded p-4 h-64" />
    </div>
  )
}

/** Compact start / peak / trough / final readout under the equity chart. */
function CurveStats({ run }: { run: RunDetail }) {
  const curve = run.equity_curve
  if (curve.length === 0) return null
  const equities = curve.map((p) => p.equity)
  const start = equities[0]
  const final = equities[equities.length - 1]
  const peak = Math.max(...equities)
  const trough = Math.min(...equities)

  const items: { label: string; value: string; cls?: string }[] = [
    { label: 'Start', value: formatCurrency(start) },
    { label: 'Peak', value: formatCurrency(peak), cls: 'text-positive' },
    { label: 'Trough', value: formatCurrency(trough), cls: 'text-negative' },
    { label: 'Final', value: formatCurrency(final), cls: returnClass(final - start) },
  ]

  return (
    <div className="mt-4 pt-3 border-t border-hairline grid grid-cols-2 sm:grid-cols-4 gap-3">
      {items.map((it) => (
        <div key={it.label}>
          <dt className="text-[11px] text-ink-subtle uppercase tracking-wider">{it.label}</dt>
          <dd className={`font-mono text-sm font-medium mt-0.5 ${it.cls ?? 'text-ink'}`}>
            {it.value}
          </dd>
        </div>
      ))}
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
      <div className="bg-surface border border-hairline rounded p-8 text-center">
        <p className="text-sm text-ink-muted mb-3">Backtest #{id ?? ''} not found.</p>
        <Link to="/backtests" className="text-sm text-accent hover:text-accent-bright transition-colors">
          ← Back to Backtests
        </Link>
      </div>
    )
  }

  if (error !== null) {
    return (
      <div className="bg-surface border border-hairline rounded p-5">
        <p role="alert" className="text-sm text-negative mb-3">{error}</p>
        <Link to="/backtests" className="text-sm text-accent hover:text-accent-bright transition-colors">
          ← Back to Backtests
        </Link>
      </div>
    )
  }

  if (run === null) return null

  const retClass = returnClass(run.total_return_pct)
  const curve = run.equity_curve
  const range =
    curve.length > 0
      ? `${formatDate(curve[0].timestamp)} → ${formatDate(curve[curve.length - 1].timestamp)}`
      : '—'

  const provenance: ProvenanceItem[] = [
    { label: 'Run', value: `#${run.id}` },
    { label: 'Strategy', value: run.strategy_name },
    { label: 'Period', value: range },
    { label: 'Bars', value: curve.length > 0 ? curve.length : null },
    { label: 'Capital', value: formatCurrency(run.initial_capital) },
    { label: 'Round trips', value: run.metrics.num_round_trips },
    { label: 'Mode', value: 'Simulated' },
  ]

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <Link
          to="/backtests"
          className="inline-block text-xs text-ink-subtle hover:text-ink-muted transition-colors mb-2"
        >
          ← Backtests
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <h1 className="text-xl font-semibold text-ink font-mono">{run.symbol}</h1>
              <RunStatusBadge status={run.status} />
            </div>
            <p className="text-sm text-ink-subtle">
              {run.strategy_name} · created {formatDate(run.created_at)}
            </p>
          </div>
          <div className="text-right">
            <p className={`font-mono text-2xl font-bold ${retClass}`}>
              {formatSignedPercent(run.total_return_pct)}
            </p>
            <p className="text-xs text-ink-subtle mt-0.5">total return (simulated)</p>
          </div>
        </div>
      </div>

      {/* What you're looking at */}
      <p className="text-sm text-ink-muted max-w-3xl -mt-4">
        The full report for one simulated run: how the account grew, how risky the
        path was, and every trade it made — all net of fees and slippage. Each
        metric below carries a one-line plain-English definition.
      </p>

      {/* Provenance */}
      <ProvenanceStrip items={provenance} />

      {/* Grouped performance metrics */}
      <MetricsCards run={run} />

      {/* Equity curve */}
      <section aria-labelledby="curve-heading">
        <SectionHeader
          id="curve-heading"
          title="Equity Curve"
          subtitle="Account value at each bar, marked-to-market including any open position."
        />
        <div className="bg-surface border border-hairline rounded p-4">
          <EquityCurve data={run.equity_curve} />
          <CurveStats run={run} />
        </div>
      </section>

      {/* Trades */}
      <section aria-labelledby="trades-heading">
        <SectionHeader
          id="trades-heading"
          title={`Trades · ${run.trades.length} fills`}
          subtitle="Every order execution in sequence, with the cost paid on each fill."
        />
        <div className="bg-surface border border-hairline rounded p-4">
          <TradeTable trades={run.trades} />
        </div>
      </section>

      {/* Config */}
      {Object.keys(run.config).length > 0 && (
        <section aria-labelledby="config-heading">
          <SectionHeader
            id="config-heading"
            title="Strategy Configuration"
            subtitle="The exact parameters this run was executed with."
          />
          <div className="bg-surface border border-hairline rounded p-4">
            <dl className="grid grid-cols-2 sm:grid-cols-3 gap-y-3 gap-x-6">
              {Object.entries(run.config).map(([key, value]) => (
                <div key={key}>
                  <dt className="text-[11px] text-ink-subtle uppercase tracking-wider">
                    {prettyKey(key)}
                  </dt>
                  <dd className="font-mono text-sm text-ink mt-0.5">
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
