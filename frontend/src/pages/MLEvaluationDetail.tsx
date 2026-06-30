import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getMLEvaluation } from '../api/ml'
import type {
  MLEvaluationDetail as MLEvalDetailType,
  MLSignificanceBlock,
  MLSplitResult,
  MLSkippedSplit,
  MLVerdict,
  MLWalkForwardResult,
} from '../types/ml'
import { MLDisclaimer } from '../components/MLDisclaimer'
import { RunStatusBadge } from '../components/RunStatusBadge'
import {
  PageHeader,
  ProvenanceStrip,
  SectionHeader,
  Stat,
  StatGrid,
  Table,
  Td,
  Th,
} from '../components/ui'
import type { ProvenanceItem } from '../components/ui'
import { usePolling } from '../hooks/usePolling'
import { formatDate, formatPercent, formatSignedPercent } from '../utils/format'
import { extractMessage, isNotFound } from '../utils/errors'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const BASELINE_LABELS: Record<string, string> = {
  buy_and_hold: 'Buy & Hold',
  rule: 'Rule (Trend)',
  logistic_floor: 'Logistic Floor',
}

function baselineLabel(key: string): string {
  return BASELINE_LABELS[key] ?? key.replace(/_/g, ' ')
}

function isActive(status: string): boolean {
  return status === 'queued' || status === 'running'
}

function kindLabel(kind: string): string {
  if (kind === 'ml_walk_forward') return 'Walk-Forward ML'
  if (kind === 'ml_backtest') return 'ML Backtest'
  if (kind === 'ml_portfolio_wf') return 'Portfolio ML Walk-Forward'
  return kind
}

function fmtNum(v: number | undefined, decimals = 2): string {
  if (v === undefined || !Number.isFinite(v)) return '—'
  return v.toFixed(decimals)
}

// ---------------------------------------------------------------------------
// Verdict block — three distinct states, each as forceful as the others
// ---------------------------------------------------------------------------

interface VerdictConfig {
  label: string
  description: string
  extra?: string
  bg: string
  border: string
  textColor: string
  badgeClass: string
}

const VERDICT_CONFIGS: Record<MLVerdict, VerdictConfig> = {
  pass: {
    label: 'PASS',
    description:
      'The model passed the full significance battery net of costs: it beat all baselines in aggregate, the deflated Sharpe is positive, PBO is low, and it ranked above the Monte-Carlo random ensemble. This means the strategy survived this significance battery — nothing more. It is not a signal to trade real money.',
    bg: 'bg-emerald-950/70',
    border: 'border-emerald-800',
    textColor: 'text-emerald-400',
    badgeClass: 'bg-emerald-950 text-emerald-400 border border-emerald-800',
  },
  fail: {
    label: 'FAIL',
    description:
      'The model did not beat one or more baselines net of costs, or failed the statistical significance tests. There is insufficient evidence of edge in this dataset for this configuration.',
    bg: 'bg-rose-950/70',
    border: 'border-rose-800',
    textColor: 'text-rose-400',
    badgeClass: 'bg-rose-950 text-rose-400 border border-rose-800',
  },
  inconclusive: {
    label: 'INCONCLUSIVE',
    description:
      'The model was indistinguishable from noise. This is the EXPECTED outcome on thin daily data.',
    extra:
      'This is not a near-miss or a soft pass — it is a research dead-end on this dataset and configuration. Increase the history, widen the symbol pool, or reconsider the feature set. Do not interpret "inconclusive" as "almost passed."',
    bg: 'bg-amber-950/70',
    border: 'border-amber-800',
    textColor: 'text-amber-400',
    badgeClass: 'bg-amber-950 text-amber-400 border border-amber-800',
  },
}

function VerdictBlock({
  verdict,
  reasons,
}: {
  verdict: MLVerdict
  reasons: string[]
}) {
  const cfg = VERDICT_CONFIGS[verdict]
  return (
    <section
      aria-labelledby="verdict-heading"
      className={`rounded border ${cfg.border} ${cfg.bg} p-5 space-y-3`}
    >
      <div className="flex items-center gap-3">
        <h2
          id="verdict-heading"
          className={`text-2xl font-semibold font-mono tracking-tight ${cfg.textColor}`}
        >
          {cfg.label}
        </h2>
        <span
          className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-mono font-medium ${cfg.badgeClass}`}
        >
          {verdict}
        </span>
      </div>
      <p className="text-sm text-zinc-300 leading-relaxed">{cfg.description}</p>
      {cfg.extra && (
        <p className="text-sm font-medium text-amber-300/90 leading-relaxed border-l-2 border-amber-700 pl-3">
          {cfg.extra}
        </p>
      )}
      {reasons.length > 0 && (
        <ul
          aria-label="Verdict reasons"
          className="space-y-1 mt-2"
        >
          {reasons.map((r, i) => (
            <li
              key={i}
              className="flex items-start gap-2 text-xs text-zinc-400 leading-relaxed"
            >
              <span className={`mt-0.5 shrink-0 ${cfg.textColor}`} aria-hidden="true">
                ›
              </span>
              {r}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------
// Model vs baselines comparison
// ---------------------------------------------------------------------------

/**
 * Map a baseline key (e.g. "logistic_floor") to the shortname used in the
 * aggregate_model dict (e.g. "logistic"). The backend abbreviates the logistic
 * floor key in aggregate_model to avoid the double-word.
 */
function aggModelKey(
  baselineKey: string,
  prefix: 'splits_beating' | 'beats',
): string {
  const short = baselineKey === 'logistic_floor' ? 'logistic' : baselineKey
  return `${prefix}_${short}`
}

function BaselineComparison({ results }: { results: MLWalkForwardResult }) {
  const { aggregate_model: am, aggregate_baselines: ab } = results
  const n = am.n_splits_evaluated ?? 0

  const baselines = Object.entries(ab)

  return (
    <section aria-labelledby="baselines-heading" className="space-y-3">
      <SectionHeader
        id="baselines-heading"
        title="Model vs Baselines — Aggregate"
        subtitle="Compounded out-of-sample total return, net of the same fees and slippage applied to every strategy. This is the primary verdict basis."
      />
      <div className="bg-zinc-900 border border-zinc-800 rounded px-4 py-3">
        <Table>
          <thead>
            <tr className="border-b border-zinc-800">
              <Th>Strategy</Th>
              <Th align="right">Total Return</Th>
              <Th align="right">Turnover</Th>
              <Th align="right">OOS Trades</Th>
              <Th align="right">Beats (splits)</Th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800/60">
            {/* Model row */}
            <tr className="bg-zinc-800/20">
              <Td className="text-zinc-50 font-medium">Model</Td>
              <Td mono align="right" className={returnColorClass(am.total_return_pct)}>
                {formatSignedPercent(am.total_return_pct ?? 0)}
              </Td>
              <Td mono align="right" className="text-zinc-400">
                {fmtNum(am.mean_turnover_annualized)}×/yr
              </Td>
              <Td mono align="right" className="text-zinc-400">
                {Math.round(am.num_oos_round_trips ?? 0)}
              </Td>
              <Td mono align="right" className="text-zinc-500">
                —
              </Td>
            </tr>
            {/* Baseline rows */}
            {baselines.map(([key, bm]) => {
              const wins = am[aggModelKey(key, 'splits_beating')]
              const beats = (am[aggModelKey(key, 'beats')] ?? 0) > 0.5
              return (
                <tr key={key} className="hover:bg-zinc-800/10 transition-colors">
                  <Td className="text-zinc-400">{baselineLabel(key)}</Td>
                  <Td mono align="right" className="text-zinc-400">
                    {formatSignedPercent(bm.total_return_pct ?? 0)}
                  </Td>
                  <Td mono align="right" className="text-zinc-500">
                    {fmtNum(bm.mean_turnover_annualized)}×/yr
                  </Td>
                  <Td mono align="right" className="text-zinc-500">
                    {Math.round(bm.num_oos_round_trips ?? 0)}
                  </Td>
                  <Td mono align="right">
                    <span
                      className={
                        beats ? 'text-emerald-400' : 'text-rose-400'
                      }
                    >
                      {beats ? 'Yes' : 'No'}
                      {wins !== undefined && n > 0 ? (
                        <span className="text-zinc-500 ml-1">
                          ({Math.round(wins)}/{Math.round(n)})
                        </span>
                      ) : null}
                    </span>
                  </Td>
                </tr>
              )
            })}
            {/* MC ensemble pseudo-row — turnover goes in the Turnover column, not Total Return */}
            <tr className="hover:bg-zinc-800/10 transition-colors">
              <Td className="text-zinc-500 italic text-xs">MC Ensemble (random null)</Td>
              <Td mono align="right" className="text-zinc-500">—</Td>
              <Td mono align="right" className="text-zinc-500 text-xs">
                {fmtNum(am.mc_mean_turnover_annualized)}×/yr
              </Td>
              <Td mono align="right" className="text-zinc-500">—</Td>
              <Td mono align="right" className="text-zinc-500">—</Td>
            </tr>
          </tbody>
        </Table>
      </div>
    </section>
  )
}

function returnColorClass(v: number | undefined): string {
  if (v === undefined) return 'text-zinc-300'
  if (v > 0) return 'text-emerald-400'
  if (v < 0) return 'text-rose-400'
  return 'text-zinc-300'
}

// ---------------------------------------------------------------------------
// Significance block
// ---------------------------------------------------------------------------

function SignificanceSection({ sig }: { sig: MLSignificanceBlock }) {
  return (
    <section aria-labelledby="sig-heading" className="space-y-3">
      <SectionHeader
        id="sig-heading"
        title="Statistical Significance (§8)"
        subtitle="The battery of tests behind the verdict. Deflated Sharpe and PBO are the primary gatekeepers."
      />
      <StatGrid cols="grid-cols-2 md:grid-cols-3 lg:grid-cols-4">
        <Stat
          label="Deflated Sharpe (DSR)"
          value={fmtNum(sig.deflated_sharpe)}
          tone={
            sig.deflated_sharpe > 0
              ? 'pos'
              : sig.deflated_sharpe < 0
                ? 'neg'
                : 'default'
          }
          hint="Multiple-testing-adjusted Sharpe. Positive = evidence of edge after accounting for the search space. Negative = noise."
        />
        <Stat
          label="PBO"
          value={formatPercent(sig.pbo * 100)}
          tone={sig.pbo < 0.5 ? 'pos' : 'neg'}
          hint="Probability of Backtest Overfitting (CSCV). Fraction of strategy resamples that rank lower OOS than IS. High PBO = likely overfit."
        />
        <Stat
          label="MC Percentile"
          value={formatPercent(sig.mc_percentile * 100)}
          tone={sig.mc_percentile > 0.5 ? 'pos' : 'default'}
          hint="Where the model ranks among 200+ random long/flat strategies with the same in-market fraction. Above 50% = beats noise."
        />
        <Stat
          label="Effective N"
          value={fmtNum(sig.n_eff, 0)}
          unit="bars"
          hint="Uniqueness-adjusted effective sample size (overlapping H-day labels shrink this below the raw bar count)."
        />
        <Stat
          label="Raw OOS Bars"
          value={String(sig.n_obs)}
          hint="Total OOS bar count concatenated across all splits (unadjusted for label overlap)."
        />
        <Stat
          label="Config Trials (N)"
          value={String(sig.n_config_trials)}
          hint="Documented search space size used in the DSR multiple-testing penalty. Larger N raises the bar for a pass."
        />
        <Stat
          label="OOS Round Trips"
          value={String(sig.n_oos_round_trips)}
          hint="Total completed model round-trip trades across all non-skipped splits."
        />
        <Stat
          label="Raw OOS Sharpe"
          value={fmtNum(sig.sharpe)}
          hint="Per-period Sharpe before multiple-testing deflation."
        />
        <Stat
          label="Return Skew"
          value={fmtNum(sig.skew)}
          hint="Asymmetry of OOS per-bar returns. Positive = occasional large wins; negative = occasional large losses."
        />
        <Stat
          label="Return Kurtosis"
          value={fmtNum(sig.kurtosis)}
          hint="Tail heaviness (3.0 = Gaussian). Higher = fatter tails."
        />
        <Stat
          label="Var Trial Sharpes"
          value={fmtNum(sig.var_trial_sharpes)}
          hint="Variance of per-split Sharpe estimates; feeds the DSR cross-split dispersion correction."
        />
      </StatGrid>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Per-split distribution table
// ---------------------------------------------------------------------------

function SplitsTable({ splits }: { splits: MLSplitResult[] }) {
  if (splits.length === 0) {
    return (
      <p className="text-sm text-zinc-500">
        No evaluated splits (all were skipped or the dataset was too short).
      </p>
    )
  }

  const baselineKeys = Object.keys(splits[0]?.baselines ?? {})

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded px-4 py-3">
      <Table maxHeight="24rem">
        <thead>
          <tr className="border-b border-zinc-800">
            <Th sticky className="sticky left-0 bg-zinc-950 z-20">Test Window</Th>
            <Th sticky align="right">OOS Bars</Th>
            <Th sticky align="right" sub="model">Return</Th>
            {baselineKeys.map((k) => (
              <Th key={k} sticky align="right" sub={baselineLabel(k)}>
                Return
              </Th>
            ))}
            {baselineKeys.map((k) => (
              <Th key={`b-${k}`} sticky align="right" sub={baselineLabel(k)}>
                Beats?
              </Th>
            ))}
            <Th sticky align="right">Trades</Th>
            <Th sticky align="right">No Leakage?</Th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-800/60">
          {splits.map((s, i) => (
            <tr key={i} className="align-top hover:bg-zinc-800/20 transition-colors">
              <Td mono className="text-zinc-400 whitespace-nowrap sticky left-0 bg-zinc-900 z-10">
                {s.test_start.slice(0, 10)}
                <span className="text-zinc-600">–</span>
                {s.test_end.slice(0, 10)}
              </Td>
              <Td mono align="right" className="text-zinc-500">
                {s.n_oos_bars}
              </Td>
              <Td mono align="right" className={returnColorClass(s.model.total_return_pct)}>
                {formatSignedPercent(s.model.total_return_pct)}
              </Td>
              {baselineKeys.map((k) => (
                <Td key={k} mono align="right" className="text-zinc-500">
                  {formatSignedPercent(
                    s.baselines[k]?.total_return_pct ?? 0,
                  )}
                </Td>
              ))}
              {baselineKeys.map((k) => (
                <Td key={`b-${k}`} mono align="right">
                  <span
                    className={
                      s.beats[k] ? 'text-emerald-400' : 'text-rose-400'
                    }
                  >
                    {s.beats[k] ? 'Yes' : 'No'}
                  </span>
                </Td>
              ))}
              <Td mono align="right" className="text-zinc-500">
                {s.model.oos_round_trips}
              </Td>
              <Td mono align="right">
                <span
                  className={
                    s.no_look_ahead ? 'text-emerald-400' : 'text-rose-400'
                  }
                >
                  {s.no_look_ahead ? 'Yes' : 'NO'}
                </span>
              </Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Skipped splits
// ---------------------------------------------------------------------------

function SkippedSection({ skipped }: { skipped: MLSkippedSplit[] }) {
  if (skipped.length === 0) return null
  return (
    <section aria-labelledby="skipped-heading" className="space-y-3">
      <SectionHeader
        id="skipped-heading"
        title="Skipped Splits"
        subtitle="Splits where the model could not be trained (e.g. a single-class in-sample fold). These are excluded from all aggregate metrics."
      />
      <div className="bg-zinc-900 border border-zinc-800 rounded px-4 py-3">
        <Table>
          <thead>
            <tr className="border-b border-zinc-800">
              <Th>Test Window</Th>
              <Th>Reason</Th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800/60">
            {skipped.map((s, i) => (
              <tr key={i}>
                <Td mono className="text-zinc-500 whitespace-nowrap">
                  {s.test_start.slice(0, 10)}–{s.test_end.slice(0, 10)}
                </Td>
                <Td className="text-zinc-400 text-xs">{s.reason}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Classification diagnostics (secondary, de-emphasized)
// ---------------------------------------------------------------------------

function ClassificationSection({ splits }: { splits: MLSplitResult[] }) {
  const withMetrics = splits.filter(
    (s) => Number.isFinite(s.classification.auc) && s.classification.auc > 0,
  )
  if (withMetrics.length === 0) return null

  return (
    <section aria-labelledby="clf-heading" className="space-y-3">
      <SectionHeader
        id="clf-heading"
        title="Classification Diagnostics (AUC / Brier) — Secondary Context Only"
        subtitle="These are label-prediction metrics, not the verdict. A high AUC does not mean the model makes money net of costs. The verdict is determined solely by OOS return vs baselines and the significance battery above."
      />
      <div
        role="note"
        className="bg-zinc-900 border border-zinc-700 rounded p-3"
      >
        <p className="text-xs text-zinc-500">
          AUC and Brier score measure how well the model predicts the directional
          label — they say nothing about whether those predictions are profitable
          after fees and slippage. These are diagnostic context only, shown
          de-emphasized for completeness.
        </p>
      </div>
      <div className="bg-zinc-900 border border-zinc-800 rounded px-4 py-3">
        <Table>
          <thead>
            <tr className="border-b border-zinc-800">
              <Th>Split</Th>
              <Th align="right">AUC</Th>
              <Th align="right">Brier</Th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800/60">
            {splits.map((s, i) => (
              <tr key={i}>
                <Td mono className="text-zinc-500">
                  {s.test_start.slice(0, 10)}–{s.test_end.slice(0, 10)}
                </Td>
                <Td mono align="right" className="text-zinc-500">
                  {Number.isFinite(s.classification.auc)
                    ? s.classification.auc.toFixed(3)
                    : '—'}
                </Td>
                <Td mono align="right" className="text-zinc-500">
                  {Number.isFinite(s.classification.brier)
                    ? s.classification.brier.toFixed(3)
                    : '—'}
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Full results view
// ---------------------------------------------------------------------------

function WalkForwardResults({ results }: { results: MLWalkForwardResult }) {
  const verdict = results.verdict ?? 'inconclusive'

  return (
    <div className="space-y-6">
      <VerdictBlock
        verdict={verdict as MLVerdict}
        reasons={results.reasons ?? []}
      />

      <BaselineComparison results={results} />

      <section aria-labelledby="splits-heading" className="space-y-3">
        <SectionHeader
          id="splits-heading"
          title="Per-Split Distribution"
          subtitle="Each walk-forward window's model and baseline OOS returns. A single outsized split can carry the aggregate — check the individual rows. Highlighted in red if the model lost to a baseline in that window."
        />
        <SplitsTable splits={results.splits} />
      </section>

      <SkippedSection skipped={results.skipped} />

      {results.significance && (
        <SignificanceSection sig={results.significance} />
      )}

      <ClassificationSection splits={results.splits} />

      <p className="text-xs text-zinc-600 border-t border-zinc-800 pt-4">
        All results are simulated and out-of-sample, net of fees and slippage.
        Inconclusive is the expected outcome on thin daily data. A pass here is
        not a signal to trade real money. Not financial advice.
      </p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// API-only kind notice (ml_backtest / ml_portfolio_wf)
// ---------------------------------------------------------------------------

/**
 * Shown for completed runs whose kind is not yet rendered in the UI
 * (ml_backtest and ml_portfolio_wf). Rather than the misleading
 * "results not available", we tell the user explicitly that the data
 * exists and where to find it, and we surface any headline numbers
 * present in the results JSON.
 */
function ApiOnlyKindNote({
  kind,
  results,
}: {
  kind: string
  results: Record<string, unknown>
}) {
  const totalReturn = typeof results.total_return_pct === 'number'
    ? results.total_return_pct
    : undefined
  const numTrades = typeof results.num_trades === 'number'
    ? results.num_trades
    : undefined
  const beatsAll =
    typeof results.beats_all_baselines === 'boolean'
      ? results.beats_all_baselines
      : undefined
  const dsr =
    typeof (results.significance as Record<string, unknown> | undefined)
      ?.deflated_sharpe === 'number'
      ? ((results.significance as Record<string, unknown>).deflated_sharpe as number)
      : undefined

  return (
    <div className="space-y-4">
      <div
        role="note"
        className="bg-zinc-900 border border-zinc-700 rounded p-5 space-y-2"
      >
        <p className="text-sm font-medium text-zinc-300">
          {kindLabel(kind)} results are not viewable in the UI yet.
        </p>
        <p className="text-sm text-zinc-500">
          This evaluation completed successfully. Inspect its full results via
          the API:{' '}
          <code className="font-mono text-xs text-zinc-400">
            GET /ml/evaluations/{'{id}'}
          </code>
          . The result JSON is stored in the{' '}
          <code className="font-mono text-xs text-zinc-400">results</code>{' '}
          field of the response.
        </p>
      </div>

      {/* Headline numbers that are present in the results blob */}
      {(totalReturn !== undefined ||
        numTrades !== undefined ||
        beatsAll !== undefined ||
        dsr !== undefined) && (
        <section aria-labelledby="api-only-headline" className="space-y-3">
          <SectionHeader
            id="api-only-headline"
            title="Headline Numbers"
            subtitle="Available from the results JSON. These are simulated figures — not financial advice."
          />
          <StatGrid cols="grid-cols-2 md:grid-cols-4">
            {totalReturn !== undefined && (
              <Stat
                label="Total Return"
                value={formatSignedPercent(totalReturn)}
                tone={totalReturn > 0 ? 'pos' : totalReturn < 0 ? 'neg' : 'default'}
                hint="Simulated total return net of fees and slippage."
              />
            )}
            {numTrades !== undefined && (
              <Stat
                label="Trades"
                value={String(numTrades)}
                hint="Number of round-trip trades executed in the backtest."
              />
            )}
            {beatsAll !== undefined && (
              <Stat
                label="Beats All Baselines"
                value={beatsAll ? 'Yes' : 'No'}
                tone={beatsAll ? 'pos' : 'neg'}
                hint="Whether the portfolio ML model beat every baseline in aggregate."
              />
            )}
            {dsr !== undefined && (
              <Stat
                label="Deflated Sharpe (DSR)"
                value={fmtNum(dsr)}
                tone={dsr > 0 ? 'pos' : dsr < 0 ? 'neg' : 'default'}
                hint="Multiple-testing-adjusted Sharpe. Positive = evidence of edge after accounting for the search space."
              />
            )}
          </StatGrid>
        </section>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function MLEvaluationDetail() {
  const { id } = useParams()
  const evalId = Number(id)

  const [active, setActive] = useState(true)
  const { data, error, loading } = usePolling<MLEvalDetailType>(
    () => getMLEvaluation(evalId),
    { active, intervalMs: 2000 },
  )

  useEffect(() => {
    if (data) setActive(isActive(data.status))
  }, [data])

  const hasWalkForwardResults =
    data?.status === 'completed' &&
    data.kind === 'ml_walk_forward' &&
    data.results.verdict !== undefined

  const isApiOnlyKind =
    data?.status === 'completed' &&
    (data.kind === 'ml_backtest' || data.kind === 'ml_portfolio_wf')

  const provenance: ProvenanceItem[] = data
    ? [
        { label: 'Eval', value: `#${data.id}` },
        { label: 'Kind', value: kindLabel(data.kind) },
        { label: 'Symbol', value: data.symbol },
        { label: 'Strategy', value: data.strategy_name },
        { label: 'Created', value: formatDate(data.created_at) },
      ]
    : []

  return (
    <div className="space-y-6">
      {/* Disclaimer appears in all states (loading / error / results). */}
      <MLDisclaimer />

      {loading && data === null ? (
        <div
          className="bg-zinc-900 border border-zinc-800 rounded p-8 text-center motion-safe:animate-pulse"
          aria-busy="true"
        >
          <p className="text-sm text-zinc-500">Loading evaluation…</p>
        </div>
      ) : error ? (
        <div className="space-y-3">
          <Link
            to="/ml"
            className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
          >
            ← ML Models
          </Link>
          <div className="bg-zinc-900 border border-zinc-800 rounded p-5">
            <p role="alert" className="text-sm text-rose-400">
              {isNotFound(error)
                ? `ML evaluation ${evalId} not found.`
                : extractMessage(error)}
            </p>
          </div>
        </div>
      ) : data ? (
        <>
          <PageHeader
            back={{ to: '/ml', label: 'ML Models' }}
            title={
              <span className="font-mono">
                {data.symbol}{' '}
                <span className="text-zinc-500 text-base font-normal">
                  · {kindLabel(data.kind)}
                </span>
              </span>
            }
            subtitle={`${data.strategy_name} — simulated, out-of-sample, net of costs`}
            meta={<RunStatusBadge status={data.status} />}
          />

          <ProvenanceStrip items={provenance} />

          {isActive(data.status) ? (
            <div className="bg-zinc-900 border border-zinc-800 rounded p-8 text-center">
              <span
                className="inline-block h-4 w-4 border-2 border-zinc-600 border-t-amber-400 rounded-full motion-safe:animate-spin mb-3"
                aria-hidden="true"
              />
              <p className="text-sm text-zinc-400">
                {data.status === 'queued'
                  ? 'Queued — waiting for a worker…'
                  : 'Running walk-forward evaluation — this can take several minutes…'}{' '}
                This page updates automatically.
              </p>
            </div>
          ) : data.status === 'failed' ? (
            <div className="bg-zinc-900 border border-rose-900/50 rounded p-5">
              <p role="alert" className="text-sm text-rose-400">
                This evaluation failed. Check the worker logs for the cause.
              </p>
            </div>
          ) : hasWalkForwardResults ? (
            <WalkForwardResults
              results={data.results as MLWalkForwardResult}
            />
          ) : isApiOnlyKind ? (
            <ApiOnlyKindNote
              kind={data.kind}
              results={data.results as Record<string, unknown>}
            />
          ) : (
            <div className="bg-zinc-900 border border-zinc-800 rounded p-5">
              <p className="text-sm text-zinc-500">
                Evaluation completed but results are not available. Status:{' '}
                <code className="font-mono text-xs">{data.status}</code>
              </p>
            </div>
          )}
        </>
      ) : null}
    </div>
  )
}
