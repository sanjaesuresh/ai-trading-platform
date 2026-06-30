import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  getComparison,
  getPortfolio,
  setDeploymentEnabled,
  triggerRun,
} from '../api/paperTrading'
import { EquityCurve } from '../components/EquityCurve'
import { PaperDisclaimer } from '../components/PaperDisclaimer'
import { RunStatusBadge } from '../components/RunStatusBadge'
import { usePolling } from '../hooks/usePolling'
import type { ComparisonView, PortfolioView } from '../types/paperTrading'
import type { EquityPoint } from '../types/backtest'
import {
  formatCurrency,
  formatDate,
  formatFraction,
  formatPercent,
  formatProfitFactor,
  returnClass,
} from '../utils/format'
import { extractMessage } from '../utils/errors'

function snapToEquity(view: PortfolioView): EquityPoint[] {
  return view.equity_curve.map((s) => ({
    timestamp: s.trading_day,
    equity: s.equity,
    cash: s.cash,
    position_value: s.position_value,
  }))
}

function fmtDelta(value: number): string {
  return `${value >= 0 ? '+' : ''}${value.toFixed(4)}`
}

export default function PaperDeploymentDetail() {
  const { id } = useParams<{ id: string }>()
  const deploymentId = Number(id)

  const [active, setActive] = useState(true)
  const { data, error, loading, refetch } = usePolling<PortfolioView>(
    () => getPortfolio(deploymentId),
    { active, intervalMs: 4000 },
  )
  const [comparison, setComparison] = useState<ComparisonView | null>(null)
  const [actionMsg, setActionMsg] = useState<string | null>(null)
  const [actionErr, setActionErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // Stop polling once the deployment is halted (a terminal state); nothing more
  // will change until it is re-enabled.
  useEffect(() => {
    if (data) setActive(data.deployment.status !== 'halted')
  }, [data])

  useEffect(() => {
    void getComparison(deploymentId)
      .then(setComparison)
      .catch(() => setComparison(null))
  }, [deploymentId])

  if (loading && data === null) {
    return (
      <div className="bg-zinc-900 border border-zinc-800 rounded p-8 text-center motion-safe:animate-pulse" aria-busy="true">
        <p className="text-sm text-zinc-500">Loading deployment…</p>
      </div>
    )
  }
  if (error || data === null) {
    return (
      <p role="alert" className="text-sm text-rose-400">
        {error ? extractMessage(error) : 'Deployment not found.'}
      </p>
    )
  }

  const { deployment, positions, orders, fills, reconciliations, slippage, global_kill } = data
  const latest = data.equity_curve[data.equity_curve.length - 1]

  const runNow = async () => {
    setActionErr(null)
    setActionMsg(null)
    setBusy(true)
    try {
      const res = await triggerRun(deploymentId, 'both')
      setActionMsg(`Queued paper run (job ${res.job_id ?? 'n/a'}).`)
      setActive(true)
      refetch()
    } catch (err) {
      setActionErr(extractMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const toggleEnabled = async () => {
    setActionErr(null)
    setBusy(true)
    try {
      await setDeploymentEnabled(deploymentId, !deployment.enabled)
      refetch()
    } catch (err) {
      setActionErr(extractMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-zinc-50">{deployment.name}</h1>
          <p className="text-sm text-zinc-500 mt-1 font-mono">
            {deployment.strategy_name} · {deployment.symbols.join(', ')} ·{' '}
            {formatCurrency(deployment.starting_capital)} start
          </p>
        </div>
        <div className="flex items-center gap-2">
          <RunStatusBadge status={deployment.status} />
          <button
            type="button"
            onClick={() => void toggleEnabled()}
            disabled={busy}
            aria-busy={busy}
            className="px-3 py-1.5 text-sm font-medium rounded border border-zinc-700 text-zinc-300 hover:bg-zinc-800 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {deployment.enabled ? 'Disable' : 'Enable'}
          </button>
          <button
            type="button"
            onClick={() => void runNow()}
            disabled={busy}
            aria-busy={busy}
            className="px-3 py-1.5 text-sm font-semibold rounded bg-amber-400 text-zinc-950 hover:bg-amber-300 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {busy ? 'Working…' : 'Run now'}
          </button>
        </div>
      </div>

      <PaperDisclaimer />

      {global_kill.active && (
        <p role="alert" className="text-sm text-rose-400 bg-rose-950/30 border border-rose-900/40 rounded p-3">
          Global kill switch is ACTIVE — no new orders will be placed.
        </p>
      )}
      {deployment.status === 'halted' && (
        <p role="alert" className="text-sm text-rose-400 bg-rose-950/30 border border-rose-900/40 rounded p-3">
          Deployment halted{deployment.halt_reason ? `: ${deployment.halt_reason}` : ''}.
        </p>
      )}
      {actionMsg && <p role="status" className="text-sm text-emerald-400">{actionMsg}</p>}
      {actionErr && <p role="alert" className="text-sm text-rose-400">{actionErr}</p>}

      {/* Portfolio snapshot cards */}
      {latest && (
        <dl className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { label: 'Equity', value: formatCurrency(latest.equity), cls: 'text-zinc-50' },
            { label: 'Cash', value: formatCurrency(latest.cash), cls: 'text-zinc-50' },
            { label: 'Gross Exposure', value: formatPercent(latest.gross_exposure_pct), cls: 'text-zinc-50' },
            { label: 'Drawdown', value: `−${formatPercent(latest.drawdown_pct)}`, cls: 'text-rose-400' },
          ].map((c) => (
            <div key={c.label} className="bg-zinc-900 border border-zinc-800 rounded p-4">
              <dt className="text-xs font-medium text-zinc-500 uppercase tracking-wider mb-2">{c.label}</dt>
              <dd className={`text-xl font-mono font-semibold ${c.cls}`}>{c.value}</dd>
            </div>
          ))}
        </dl>
      )}

      {/* Live equity curve */}
      <section aria-labelledby="equity-heading">
        <h2 id="equity-heading" className="text-xs font-medium text-zinc-500 uppercase tracking-wider mb-3">
          Simulated Paper Equity
        </h2>
        <div className="bg-zinc-900 border border-zinc-800 rounded p-4">
          <EquityCurve data={snapToEquity(data)} />
        </div>
      </section>

      {/* Live vs backtest comparison */}
      <section aria-labelledby="cmp-heading">
        <h2 id="cmp-heading" className="text-xs font-medium text-zinc-500 uppercase tracking-wider mb-3">
          Paper Results vs Historical Backtest
        </h2>
        <div className="bg-zinc-900 border border-zinc-800 rounded p-5 space-y-4">
          {comparison?.backtest_expectation ? (
            <dl className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {[
                { label: 'Backtest Return', value: formatPercent(comparison.backtest_expectation.total_return_pct), cls: returnClass(comparison.backtest_expectation.total_return_pct) },
                { label: 'Backtest Sharpe', value: comparison.backtest_expectation.sharpe_ratio.toFixed(2), cls: 'text-zinc-50' },
                { label: 'Backtest Max DD', value: `−${formatPercent(comparison.backtest_expectation.max_drawdown_pct)}`, cls: 'text-rose-400' },
                { label: 'Backtest Win Rate', value: formatFraction(comparison.backtest_expectation.win_rate), cls: 'text-zinc-50', note: `${comparison.backtest_expectation.num_round_trips} round trips · PF ${formatProfitFactor(comparison.backtest_expectation.profit_factor)}` },
              ].map((c) => (
                <div key={c.label}>
                  <dt className="text-xs text-zinc-500 uppercase tracking-wider mb-1">{c.label}</dt>
                  <dd className={`text-lg font-mono font-semibold ${c.cls}`}>{c.value}</dd>
                  {c.note && <p className="text-xs text-zinc-500 mt-1">{c.note}</p>}
                </div>
              ))}
            </dl>
          ) : (
            <p className="text-sm text-zinc-500">
              No historical backtest available yet (no stored history for this basket).
              A backtest is not a prediction of paper results.
            </p>
          )}

          <div className="border-t border-zinc-800 pt-4">
            <p className="text-xs text-zinc-500 uppercase tracking-wider mb-2">
              Slippage attribution — realized fill vs modeled open, per share (USD,
              cost-signed)
            </p>
            {slippage.count > 0 ? (
              <div className="grid grid-cols-2 md:grid-cols-5 gap-3 font-mono text-sm">
                <div><span className="text-zinc-500 text-xs block">fills</span>{slippage.count}</div>
                <div><span className="text-zinc-500 text-xs block">mean</span>{fmtDelta(slippage.mean)}</div>
                <div><span className="text-zinc-500 text-xs block">median</span>{fmtDelta(slippage.median)}</div>
                <div><span className="text-zinc-500 text-xs block">min</span>{fmtDelta(slippage.min)}</div>
                <div><span className="text-zinc-500 text-xs block">max</span>{fmtDelta(slippage.max)}</div>
              </div>
            ) : (
              <p className="text-sm text-zinc-500">No fills recorded yet.</p>
            )}
            <p className="text-xs text-zinc-500 mt-3 leading-relaxed">
              {comparison?.caveat ??
                'The backtest models a next-open fill; paper fills against real quotes and does not simulate dividends, market impact, latency, or queue position. The slippage distribution is the measured backtest↔paper gap; the paper↔live gap is larger and not modeled. Positive slippage = adverse cost. Simulated only.'}
            </p>
          </div>
        </div>
      </section>

      {/* Positions */}
      <Table
        heading="Open Positions"
        empty="No open positions."
        cols={['Symbol', 'Qty', 'Avg Entry', 'Market Value', 'Price']}
        rows={positions.map((p) => [p.symbol, p.quantity.toFixed(2), formatCurrency(p.avg_entry_price), formatCurrency(p.market_value), formatCurrency(p.current_price)])}
      />

      {/* Orders */}
      <Table
        heading="Orders"
        empty="No orders yet."
        cols={['Day', 'Symbol', 'Side', 'Qty', 'Status', 'Filled']}
        rows={orders.map((o) => [formatDate(o.trading_day), o.symbol, o.side, o.intended_quantity.toFixed(0), o.status, o.filled_quantity.toFixed(0)])}
      />

      {/* Fills with slippage */}
      <Table
        heading="Fills"
        empty="No fills yet."
        cols={['Day', 'Symbol', 'Side', 'Qty', 'Fill', 'Modeled Open', 'Slippage']}
        rows={fills.map((f) => [formatDate(f.trading_day), f.symbol, f.side, f.quantity.toFixed(2), formatCurrency(f.price), formatCurrency(f.modeled_reference_price), fmtDelta(f.slippage_delta)])}
      />

      {/* Reconciliation */}
      <section aria-labelledby="recon-heading">
        <h2 id="recon-heading" className="text-xs font-medium text-zinc-500 uppercase tracking-wider mb-3">
          Reconciliation Log
        </h2>
        {reconciliations.length === 0 ? (
          <div className="bg-zinc-900 border border-zinc-800 rounded p-6 text-center">
            <p className="text-sm text-zinc-500">No divergences recorded — platform matches the broker.</p>
          </div>
        ) : (
          <div className="bg-zinc-900 border border-zinc-800 rounded overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-zinc-500 uppercase tracking-wider border-b border-zinc-800">
                  <th className="px-3 py-2 font-medium">Day</th>
                  <th className="px-3 py-2 font-medium">Kind</th>
                  <th className="px-3 py-2 font-medium">Symbol</th>
                  <th className="px-3 py-2 font-medium">Detail</th>
                </tr>
              </thead>
              <tbody>
                {reconciliations.map((r) => (
                  <tr key={r.id} className="border-b border-zinc-800/60 last:border-0">
                    <td className="px-3 py-2 font-mono text-xs text-zinc-500">{formatDate(r.trading_day)}</td>
                    <td className="px-3 py-2 text-amber-400">{r.kind}</td>
                    <td className="px-3 py-2 text-zinc-400">{r.symbol ?? '—'}</td>
                    <td className="px-3 py-2 text-zinc-400">{r.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}

interface TableProps {
  heading: string
  empty: string
  cols: string[]
  rows: string[][]
}

function Table({ heading, empty, cols, rows }: TableProps) {
  return (
    <section aria-label={heading}>
      <h2 className="text-xs font-medium text-zinc-500 uppercase tracking-wider mb-3">{heading}</h2>
      {rows.length === 0 ? (
        <div className="bg-zinc-900 border border-zinc-800 rounded p-6 text-center">
          <p className="text-sm text-zinc-500">{empty}</p>
        </div>
      ) : (
        <div className="bg-zinc-900 border border-zinc-800 rounded overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-zinc-500 uppercase tracking-wider border-b border-zinc-800">
                {cols.map((c) => (
                  <th key={c} className="px-3 py-2 font-medium">{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={i} className="border-b border-zinc-800/60 last:border-0">
                  {row.map((cell, j) => (
                    <td key={j} className="px-3 py-2 font-mono text-zinc-300">{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
