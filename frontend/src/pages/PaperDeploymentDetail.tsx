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
import { MetricStat } from '../components/MetricStat'
import {
  PageHeader,
  SectionHeader,
  Stat,
  StatGrid,
  ProvenanceStrip,
  Table,
  Th,
  Td,
} from '../components/ui'
import type { ProvenanceItem } from '../components/ui'
import { usePolling } from '../hooks/usePolling'
import type { ComparisonView, PortfolioView } from '../types/paperTrading'
import type { EquityPoint } from '../types/backtest'
import { formatCurrency, formatDate, formatPercent } from '../utils/format'
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

interface Col {
  label: string
  align?: 'left' | 'right'
  sub?: string
}

/** Section + card + dense table for the simple position/order/fill lists. */
function ListTable({
  title,
  subtitle,
  empty,
  cols,
  rows,
}: {
  title: string
  subtitle: string
  empty: string
  cols: Col[]
  rows: { key: string; cells: React.ReactNode[] }[]
}) {
  return (
    <section aria-label={title}>
      <SectionHeader title={title} subtitle={subtitle} />
      {rows.length === 0 ? (
        <div className="bg-surface border border-hairline rounded p-6 text-center">
          <p className="text-sm text-ink-subtle">{empty}</p>
        </div>
      ) : (
        <div className="bg-surface border border-hairline rounded px-4 py-3">
          <Table>
            <thead>
              <tr className="border-b border-hairline">
                {cols.map((c) => (
                  <Th key={c.label} align={c.align} sub={c.sub}>{c.label}</Th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-hairline/60">
              {rows.map((row) => (
                <tr key={row.key} className="hover:bg-raised/30 transition-colors">
                  {row.cells.map((cell, j) => (
                    <Td key={j} mono align={cols[j].align} className="text-ink-muted">{cell}</Td>
                  ))}
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
      )}
    </section>
  )
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
      <div className="bg-surface border border-hairline rounded p-8 text-center motion-safe:animate-pulse" aria-busy="true">
        <p className="text-sm text-ink-subtle">Loading deployment…</p>
      </div>
    )
  }
  if (error || data === null) {
    return (
      <p role="alert" className="text-sm text-negative">
        {error ? extractMessage(error) : 'Deployment not found.'}
      </p>
    )
  }

  const { deployment, positions, orders, fills, reconciliations, slippage, global_kill } = data
  const latest = data.equity_curve[data.equity_curve.length - 1]
  const expectation = comparison?.backtest_expectation ?? null

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

  const provenance: ProvenanceItem[] = [
    { label: 'Deployment', value: `#${deployment.id}` },
    { label: 'Strategy', value: deployment.strategy_name },
    { label: 'Basket', value: deployment.symbols.join(', ') },
    { label: 'Capital', value: formatCurrency(deployment.starting_capital) },
    { label: 'Enabled', value: deployment.enabled ? 'on' : 'off' },
    { label: 'Created', value: formatDate(deployment.created_at) },
  ]

  return (
    <div className="space-y-8">
      <PageHeader
        back={{ to: '/paper', label: 'Paper Trading' }}
        title={deployment.name}
        subtitle={`${deployment.strategy_name} · ${deployment.symbols.join(', ')} · simulated paper`}
        meta={
          <div className="flex items-center gap-2">
            <RunStatusBadge status={deployment.status} />
            <button
              type="button"
              onClick={() => void toggleEnabled()}
              disabled={busy}
              aria-busy={busy}
              className="px-3 py-1.5 text-sm font-medium rounded border border-edge text-ink-muted hover:bg-raised disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {deployment.enabled ? 'Disable' : 'Enable'}
            </button>
            <button
              type="button"
              onClick={() => void runNow()}
              disabled={busy}
              aria-busy={busy}
              className="px-3 py-1.5 text-sm font-semibold rounded bg-accent text-canvas hover:bg-accent-bright disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {busy ? 'Working…' : 'Run now'}
            </button>
          </div>
        }
      />

      <p className="text-sm text-ink-muted max-w-3xl -mt-3">
        A live (but simulated) run of this strategy. Below you can watch its
        equity, current holdings, and every order and fill as they happen, and
        compare them against the historical backtest results. The kill-switch above
        flattens everything and stops new orders instantly.
      </p>

      <ProvenanceStrip items={provenance} />

      <PaperDisclaimer />

      {global_kill.active && (
        <p role="alert" className="text-sm text-negative bg-rose-950/30 border border-rose-900/40 rounded p-3">
          Global kill switch is ACTIVE — no new orders will be placed.
        </p>
      )}
      {deployment.status === 'halted' && (
        <p role="alert" className="text-sm text-negative bg-rose-950/30 border border-rose-900/40 rounded p-3">
          Deployment halted{deployment.halt_reason ? `: ${deployment.halt_reason}` : ''}.
        </p>
      )}
      {actionMsg && <p role="status" className="text-sm text-positive">{actionMsg}</p>}
      {actionErr && <p role="alert" className="text-sm text-negative">{actionErr}</p>}

      {/* Portfolio snapshot */}
      {latest && (
        <section aria-labelledby="snapshot-heading">
          <SectionHeader
            id="snapshot-heading"
            title="Portfolio Snapshot"
            subtitle={`As of the latest simulated trading day, ${formatDate(latest.trading_day)}.`}
          />
          <StatGrid cols="grid-cols-2 md:grid-cols-3 lg:grid-cols-6">
            <Stat label="Equity" value={formatCurrency(latest.equity)} hint="Cash plus marked-to-market positions." />
            <Stat label="Cash" value={formatCurrency(latest.cash)} hint="Uninvested balance." />
            <Stat label="Position Value" value={formatCurrency(latest.position_value)} hint="Market value of open positions." />
            <Stat label="Gross Exposure" value={formatPercent(latest.gross_exposure_pct)} hint="Invested share of equity." />
            <Stat label="Open Positions" value={latest.num_positions} hint="Distinct symbols held." />
            <Stat label="Drawdown" value={`−${formatPercent(latest.drawdown_pct)}`} tone="neg" hint="Below the peak equity so far." />
          </StatGrid>
        </section>
      )}

      {/* Live equity curve */}
      <section aria-labelledby="equity-heading">
        <SectionHeader
          id="equity-heading"
          title="Simulated Paper Equity"
          subtitle="Account value per simulated trading day on Alpaca's paper endpoint."
        />
        <div className="bg-surface border border-hairline rounded p-4">
          <EquityCurve data={snapToEquity(data)} />
        </div>
      </section>

      {/* Live vs backtest comparison */}
      <section aria-labelledby="cmp-heading">
        <SectionHeader
          id="cmp-heading"
          title="Paper vs Historical Backtest"
          subtitle="What the same strategy scored on history, for context. A backtest is not a prediction of paper results."
        />
        <div className="bg-surface border border-hairline rounded p-5 space-y-5">
          {expectation ? (
            <StatGrid cols="grid-cols-2 md:grid-cols-3 lg:grid-cols-6">
              <MetricStat metricKey="total_return_pct" value={expectation.total_return_pct} />
              <MetricStat metricKey="sharpe_ratio" value={expectation.sharpe_ratio} />
              <MetricStat metricKey="max_drawdown_pct" value={expectation.max_drawdown_pct} />
              <MetricStat metricKey="win_rate" value={expectation.win_rate} />
              <MetricStat metricKey="profit_factor" value={expectation.profit_factor} />
              <MetricStat metricKey="num_round_trips" value={expectation.num_round_trips} />
            </StatGrid>
          ) : (
            <p className="text-sm text-ink-subtle">
              No historical backtest available yet (no stored history for this basket).
              A backtest is not a prediction of paper results.
            </p>
          )}

          <div className="border-t border-hairline pt-4">
            <p className="text-xs text-ink-subtle uppercase tracking-wider mb-3">
              Slippage attribution — realized fill vs modeled open, per share (USD, cost-signed)
            </p>
            {slippage.count > 0 ? (
              <StatGrid cols="grid-cols-2 sm:grid-cols-5">
                <Stat label="Fills" value={slippage.count} hint="Measured fills." />
                <Stat label="Mean" value={fmtDelta(slippage.mean)} hint="Positive = adverse cost." />
                <Stat label="Median" value={fmtDelta(slippage.median)} />
                <Stat label="Min" value={fmtDelta(slippage.min)} />
                <Stat label="Max" value={fmtDelta(slippage.max)} />
              </StatGrid>
            ) : (
              <p className="text-sm text-ink-subtle">No fills recorded yet.</p>
            )}
            <p className="text-xs text-ink-subtle mt-3 leading-relaxed">
              {comparison?.caveat ??
                'The backtest models a next-open fill; paper fills against real quotes and does not simulate dividends, market impact, latency, or queue position. The slippage distribution is the measured backtest↔paper gap; the paper↔live gap is larger and not modeled. Positive slippage = adverse cost. Simulated only.'}
            </p>
          </div>
        </div>
      </section>

      {/* Positions */}
      <ListTable
        title="Open Positions"
        subtitle="Symbols currently held, marked to the latest price."
        empty="No open positions."
        cols={[
          { label: 'Symbol' },
          { label: 'Qty', align: 'right', sub: 'shares' },
          { label: 'Avg Entry', align: 'right', sub: 'USD' },
          { label: 'Market Value', align: 'right', sub: 'USD' },
          { label: 'Price', align: 'right', sub: 'USD' },
        ]}
        rows={positions.map((p) => ({
          key: `${p.symbol}-${p.trading_day}`,
          cells: [
            p.symbol,
            p.quantity.toFixed(2),
            formatCurrency(p.avg_entry_price),
            formatCurrency(p.market_value),
            formatCurrency(p.current_price),
          ],
        }))}
      />

      {/* Orders */}
      <ListTable
        title="Orders"
        subtitle="Every order the strategy intended, and how much of it filled."
        empty="No orders yet."
        cols={[
          { label: 'Day' },
          { label: 'Symbol' },
          { label: 'Side' },
          { label: 'Qty', align: 'right', sub: 'shares' },
          { label: 'Status' },
          { label: 'Filled', align: 'right', sub: 'shares' },
        ]}
        rows={orders.map((o) => ({
          key: String(o.id),
          cells: [
            formatDate(o.trading_day),
            o.symbol,
            o.side,
            o.intended_quantity.toFixed(0),
            o.status,
            o.filled_quantity.toFixed(0),
          ],
        }))}
      />

      {/* Fills with slippage */}
      <ListTable
        title="Fills"
        subtitle="Executions against real quotes, with the gap from the backtest's modeled open."
        empty="No fills yet."
        cols={[
          { label: 'Day' },
          { label: 'Symbol' },
          { label: 'Side' },
          { label: 'Qty', align: 'right', sub: 'shares' },
          { label: 'Fill', align: 'right', sub: 'USD' },
          { label: 'Modeled Open', align: 'right', sub: 'USD' },
          { label: 'Slippage', align: 'right', sub: 'USD/sh' },
        ]}
        rows={fills.map((f) => ({
          key: String(f.id),
          cells: [
            formatDate(f.trading_day),
            f.symbol,
            f.side,
            f.quantity.toFixed(2),
            formatCurrency(f.price),
            formatCurrency(f.modeled_reference_price),
            fmtDelta(f.slippage_delta),
          ],
        }))}
      />

      {/* Reconciliation */}
      <section aria-labelledby="recon-heading">
        <SectionHeader
          id="recon-heading"
          title="Reconciliation Log"
          subtitle="Divergences between the platform's view and the broker's. Empty is good."
        />
        {reconciliations.length === 0 ? (
          <div className="bg-surface border border-hairline rounded p-6 text-center">
            <p className="text-sm text-ink-subtle">No divergences recorded — platform matches the broker.</p>
          </div>
        ) : (
          <div className="bg-surface border border-hairline rounded px-4 py-3">
            <Table>
              <thead>
                <tr className="border-b border-hairline">
                  <Th>Day</Th>
                  <Th>Kind</Th>
                  <Th>Symbol</Th>
                  <Th>Detail</Th>
                </tr>
              </thead>
              <tbody className="divide-y divide-hairline/60">
                {reconciliations.map((r) => (
                  <tr key={r.id}>
                    <Td mono className="text-ink-subtle">{formatDate(r.trading_day)}</Td>
                    <Td className="text-amber-400">{r.kind}</Td>
                    <Td className="text-ink-muted">{r.symbol ?? '—'}</Td>
                    <Td className="text-ink-muted">{r.detail}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>
        )}
      </section>
    </div>
  )
}
