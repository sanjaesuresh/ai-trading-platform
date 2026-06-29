import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getEvaluation } from '../api/evaluations'
import type {
  CombinationResult,
  DistributionSummary,
  EvaluationDetail as EvaluationDetailType,
  SplitResult,
} from '../types/evaluation'
import type { Metrics } from '../types/backtest'
import { RunStatusBadge } from '../components/RunStatusBadge'
import { usePolling } from '../hooks/usePolling'
import { formatDate, formatFraction, formatPercent } from '../utils/format'
import { extractMessage, isNotFound } from '../utils/errors'

function isActive(status: string): boolean {
  return status === 'queued' || status === 'running'
}

// Format an objective value in its own units: *_pct as a percent, win_rate as a
// fraction, ratios (sharpe, sortino, profit_factor) as a plain number.
function fmtObjective(objective: string, v: number | undefined): string {
  if (v === undefined || Number.isNaN(v)) return '—'
  if (objective.endsWith('_pct')) return formatPercent(v)
  if (objective === 'win_rate') return formatFraction(v)
  return v.toFixed(2)
}

function metricValue(m: Metrics, objective: string): number {
  return (m as unknown as Record<string, number>)[objective] ?? Number.NaN
}

function paramsLabel(p: Record<string, number>): string {
  const entries = Object.entries(p)
  if (entries.length === 0) return '(defaults)'
  return entries.map(([k, v]) => `${k}=${v}`).join(', ')
}

// The multiple-testing / overfitting caveat, shown on every completed evaluation
// so the honest framing travels with the result, not just the docs.
const MULTIPLE_TESTING_NOTE =
  'Many parameter combinations were tested, so the best in-sample cell is likely ' +
  'inflated by luck. Trust only the out-of-sample, net-of-fees distribution and ' +
  'the fraction beating the baseline — never the single best cell on its own.'

function StatCard({
  label,
  value,
  tone = 'neutral',
  note,
}: {
  label: string
  value: string
  tone?: 'neutral' | 'good' | 'bad'
  note?: string
}) {
  const cls =
    tone === 'good'
      ? 'text-emerald-400'
      : tone === 'bad'
        ? 'text-rose-400'
        : 'text-zinc-50'
  return (
    <div className="bg-zinc-950 border border-zinc-800 rounded p-3">
      <p className="text-xs text-zinc-500 uppercase tracking-wider">{label}</p>
      <p className={`font-mono text-lg font-semibold mt-1 ${cls}`}>{value}</p>
      {note && <p className="text-xs text-zinc-600 mt-1">{note}</p>}
    </div>
  )
}

function DistributionSection({
  summary,
  nCombinations,
}: {
  summary: Partial<DistributionSummary>
  nCombinations: number
}) {
  const objective = summary.objective ?? '—'
  const oos = summary.is_out_of_sample === true
  const pct = summary.pct_beating_baseline

  return (
    <section className="space-y-4">
      <div className="flex items-center gap-3">
        <h2 className="text-sm font-semibold text-zinc-200">
          Distribution of <span className="font-mono">{objective}</span>
        </h2>
        <span
          className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-mono ${
            oos
              ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
              : 'bg-amber-950 text-amber-300 border border-amber-800'
          }`}
        >
          {oos ? 'out-of-sample' : 'in-sample only'}
        </span>
      </div>

      {!oos && (
        <p className="text-sm text-amber-300/80">
          These numbers are <strong>in-sample only</strong> — a map of the grid,
          not evidence the strategy would hold up on future or out-of-sample data.
          Run a walk-forward for an out-of-sample, baseline-compared result.
        </p>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <StatCard
          label="Best"
          value={fmtObjective(objective, summary.best)}
          note={oos ? undefined : 'In-sample only — the most data-mined cell, not a result.'}
        />
        <StatCard label="Median" value={fmtObjective(objective, summary.median)} />
        <StatCard label="Worst" value={fmtObjective(objective, summary.worst)} />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard
          label="In/out-of-sample gap"
          value={fmtObjective(objective, summary.in_sample_vs_out_sample_gap)}
          note="Selected combo: in-sample minus out-of-sample."
        />
        <StatCard
          label="Overfit flag"
          value={summary.overfit_flag ? 'Flagged' : 'Not flagged'}
          tone={summary.overfit_flag ? 'bad' : 'neutral'}
          note="Not flagged is not a green light."
        />
        <StatCard
          label="Beating baseline"
          value={pct === null || pct === undefined ? 'n/a' : formatFraction(pct)}
          tone={pct != null && pct > 0.5 ? 'good' : 'neutral'}
          note={pct === null || pct === undefined ? 'No baseline (pure sweep).' : 'Out-of-sample, net of fees.'}
        />
        <StatCard label="Combinations tested" value={String(nCombinations)} />
      </div>
    </section>
  )
}

function SplitsTable({ splits, objective }: { splits: SplitResult[]; objective: string }) {
  if (splits.length === 0) {
    return <p className="text-sm text-zinc-500">No walk-forward splits fit this dataset.</p>
  }
  return (
    <section className="space-y-2">
      <h2 className="text-sm font-semibold text-zinc-200">Per-split: in-sample vs out-of-sample vs baseline</h2>
      <div className="bg-zinc-900 border border-zinc-800 rounded overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-zinc-500 uppercase tracking-wider border-b border-zinc-800">
              <th className="px-3 py-2 font-medium">Test window</th>
              <th className="px-3 py-2 font-medium">Chosen params</th>
              <th className="px-3 py-2 font-medium">In-sample</th>
              <th className="px-3 py-2 font-medium">Out-of-sample</th>
              <th className="px-3 py-2 font-medium">Baseline</th>
              <th className="px-3 py-2 font-medium">Trades (out)</th>
            </tr>
          </thead>
          <tbody>
            {splits.map((s, i) => {
              const out = metricValue(s.out_sample, objective)
              const base = metricValue(s.baseline_out_sample, objective)
              const beat = out > base
              return (
                <tr key={i} className="border-b border-zinc-800/60 last:border-0 align-top">
                  <td className="px-3 py-2 font-mono text-xs text-zinc-400">
                    {s.test_start}–{s.test_end}
                  </td>
                  <td className="px-3 py-2 font-mono text-xs text-zinc-500 max-w-xs">
                    {paramsLabel(s.chosen_params)}
                  </td>
                  <td className="px-3 py-2 font-mono text-zinc-400">
                    {fmtObjective(objective, metricValue(s.in_sample, objective))}
                  </td>
                  <td className={`px-3 py-2 font-mono ${beat ? 'text-emerald-400' : 'text-zinc-300'}`}>
                    {fmtObjective(objective, out)}
                  </td>
                  <td className="px-3 py-2 font-mono text-zinc-400">
                    {fmtObjective(objective, base)}
                  </td>
                  <td className="px-3 py-2 font-mono text-zinc-400">{s.num_trades_out}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function CombinationsTable({
  combinations,
  objective,
}: {
  combinations: CombinationResult[]
  objective: string
}) {
  if (combinations.length === 0) {
    return <p className="text-sm text-zinc-500">No combinations were evaluated.</p>
  }
  return (
    <section className="space-y-2">
      <h2 className="text-sm font-semibold text-zinc-200">All combinations (in-sample)</h2>
      <p className="text-xs text-zinc-600">
        Every cell in the grid, in evaluation order — not ranked. A sweep is
        in-sample only; the spread here is what the multiple-testing caveat is about.
      </p>
      <div className="bg-zinc-900 border border-zinc-800 rounded overflow-x-auto max-h-96 overflow-y-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-zinc-900">
            <tr className="text-left text-xs text-zinc-500 uppercase tracking-wider border-b border-zinc-800">
              <th className="px-3 py-2 font-medium">Params</th>
              <th className="px-3 py-2 font-medium">In-sample</th>
              <th className="px-3 py-2 font-medium">Out-of-sample</th>
              <th className="px-3 py-2 font-medium">Trades (in)</th>
            </tr>
          </thead>
          <tbody>
            {combinations.map((c, i) => (
              <tr key={i} className="border-b border-zinc-800/60 last:border-0">
                <td className="px-3 py-2 font-mono text-xs text-zinc-400 max-w-md">
                  {paramsLabel(c.params)}
                </td>
                <td className="px-3 py-2 font-mono text-zinc-300">
                  {fmtObjective(objective, metricValue(c.in_sample, objective))}
                </td>
                <td className="px-3 py-2 font-mono text-zinc-400">
                  {c.out_sample ? fmtObjective(objective, metricValue(c.out_sample, objective)) : '—'}
                </td>
                <td className="px-3 py-2 font-mono text-zinc-400">{c.num_trades_in}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function Results({ data }: { data: EvaluationDetailType }) {
  const { results } = data
  const summary = results.summary
  const objective = summary.objective ?? data.objective

  return (
    <div className="space-y-6">
      <div
        role="note"
        className="bg-amber-950/40 border border-amber-900/50 rounded p-4"
      >
        <p className="text-sm text-amber-300/90">
          {results.caveat && results.caveat.length > 0
            ? results.caveat
            : MULTIPLE_TESTING_NOTE}
        </p>
      </div>

      <DistributionSection summary={summary} nCombinations={results.n_combinations} />

      {data.kind === 'walk_forward' ? (
        <SplitsTable splits={results.splits ?? []} objective={objective} />
      ) : (
        <CombinationsTable combinations={results.combinations ?? []} objective={objective} />
      )}

      <p className="text-xs text-zinc-500 border-t border-zinc-800 pt-4">
        {MULTIPLE_TESTING_NOTE} Simulated only — not financial advice.
      </p>
    </div>
  )
}

export default function EvaluationDetail() {
  const { id } = useParams()
  const evalId = Number(id)

  const [active, setActive] = useState(true)
  const { data, error, loading } = usePolling<EvaluationDetailType>(
    () => getEvaluation(evalId),
    { active, intervalMs: 2000 },
  )
  useEffect(() => {
    if (data) setActive(isActive(data.status))
  }, [data])

  return (
    <div className="space-y-6">
      <Link to="/evaluations" className="text-sm text-amber-400 hover:text-amber-300">
        ← Evaluations
      </Link>

      {loading && data === null ? (
        <div className="bg-zinc-900 border border-zinc-800 rounded p-8 text-center motion-safe:animate-pulse" aria-busy="true">
          <p className="text-sm text-zinc-500">Loading evaluation…</p>
        </div>
      ) : error ? (
        <div className="bg-zinc-900 border border-zinc-800 rounded p-5">
          <p role="alert" className="text-sm text-rose-400">
            {isNotFound(error) ? `Evaluation ${evalId} not found.` : extractMessage(error)}
          </p>
        </div>
      ) : data ? (
        <>
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-xs text-zinc-500 font-mono mb-1">Evaluation #{data.id}</p>
              <h1 className="text-xl font-semibold text-zinc-50">
                {data.symbol}{' '}
                <span className="text-zinc-500 text-base font-normal">
                  · {data.kind === 'walk_forward' ? 'Walk-forward' : 'Sweep'}
                </span>
              </h1>
              <p className="text-xs text-zinc-500 mt-0.5">
                {data.strategy_name} · objective <span className="font-mono">{data.objective}</span> ·{' '}
                {formatDate(data.created_at)}
              </p>
            </div>
            <RunStatusBadge status={data.status} />
          </div>

          {isActive(data.status) ? (
            <div className="bg-zinc-900 border border-zinc-800 rounded p-8 text-center">
              <span
                className="inline-block h-4 w-4 border-2 border-zinc-600 border-t-amber-400 rounded-full motion-safe:animate-spin mb-3"
                aria-hidden="true"
              />
              <p className="text-sm text-zinc-400">
                {data.status === 'queued' ? 'Queued — waiting for a worker…' : 'Running…'} This
                page updates automatically.
              </p>
            </div>
          ) : data.status === 'failed' ? (
            <div className="bg-zinc-900 border border-rose-900/50 rounded p-5">
              <p role="alert" className="text-sm text-rose-400">
                This evaluation failed. Check the worker logs for the cause.
              </p>
            </div>
          ) : (
            <Results data={data} />
          )}
        </>
      ) : null}
    </div>
  )
}
