import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { listEvaluations } from '../api/evaluations'
import type { EvaluationSummary } from '../types/evaluation'
import { RunStatusBadge } from '../components/RunStatusBadge'
import { PageIntro, Table, Th, Td, Term } from '../components/ui'
import { usePolling } from '../hooks/usePolling'
import { formatDate } from '../utils/format'
import { extractMessage } from '../utils/errors'

function isActive(status: string): boolean {
  return status === 'queued' || status === 'running'
}

function kindLabel(kind: string): string {
  if (kind === 'walk_forward') return 'Walk-forward'
  if (kind === 'ml_walk_forward') return 'ML Walk-forward'
  if (kind === 'ml_backtest') return 'ML Backtest'
  return 'Sweep'
}

function isMLKind(kind: string): boolean {
  return kind === 'ml_walk_forward' || kind === 'ml_backtest'
}

export default function Evaluations() {
  // Poll until the first fetch tells us nothing is still queued/running.
  const [active, setActive] = useState(true)
  const { data, error, loading } = usePolling<EvaluationSummary[]>(
    listEvaluations,
    { active, intervalMs: 2500 },
  )
  useEffect(() => {
    if (data) setActive(data.some((r) => isActive(r.status)))
  }, [data])

  const list = data ?? []
  const isLoading = loading && data === null

  return (
    <div className="space-y-6">
      <PageIntro
        title="Evaluations"
        icon="🔍"
        eyebrow="Evaluations"
        meta={
          list.length > 0 ? (
            <span className="font-mono text-sm text-ink-subtle">
              {list.length} evaluation{list.length === 1 ? '' : 's'}
            </span>
          ) : undefined
        }
      >
        A single backtest is easy to fool yourself with. Evaluations are the
        stress tests: a <Term id="parameter_sweep">parameter sweep</Term> tries many
        settings, and a <Term id="walk_forward">walk-forward test</Term> checks a
        strategy on data it was never tuned on. The{' '}
        <Term id="out_of_sample">out-of-sample</Term> result is the only one that
        really counts. Simulated only — not financial advice.
      </PageIntro>

      {isLoading ? (
        <div
          className="bg-surface border border-hairline rounded p-8 text-center motion-safe:animate-pulse"
          aria-busy="true"
        >
          <p className="text-sm text-ink-subtle">Loading evaluations…</p>
        </div>
      ) : error ? (
        <div className="bg-surface border border-hairline rounded p-5">
          <p role="alert" className="text-sm text-negative">{extractMessage(error)}</p>
        </div>
      ) : list.length === 0 ? (
        <div className="bg-surface border border-hairline rounded p-8 text-center">
          <p className="text-sm text-ink-subtle">
            No evaluations yet. Trigger a sweep or walk-forward via the API
            (POST /evaluations/sweep or /walk-forward).
          </p>
        </div>
      ) : (
        <div className="bg-surface border border-hairline rounded px-4 py-3">
          <Table>
            <thead>
              <tr className="border-b border-hairline">
                <Th>ID</Th>
                <Th>Kind</Th>
                <Th>Symbol</Th>
                <Th>Strategy</Th>
                <Th>Objective</Th>
                <Th>Status</Th>
                <Th align="right">Created</Th>
                <Th align="right"><span className="sr-only">View</span></Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-hairline/60">
              {list.map((r) => (
                <tr key={r.id} className="hover:bg-raised/30 transition-colors">
                  <Td mono className="text-ink-subtle">#{r.id}</Td>
                  <Td className="text-ink-muted">{kindLabel(r.kind)}</Td>
                  <Td mono className="text-ink">{r.symbol}</Td>
                  <Td className="text-ink-muted text-xs">{r.strategy_name}</Td>
                  <Td mono className="text-ink-muted text-xs">{r.objective}</Td>
                  <Td><RunStatusBadge status={r.status} /></Td>
                  <Td mono align="right" className="text-ink-subtle">{formatDate(r.created_at)}</Td>
                  <Td align="right">
                    <Link
                      to={isMLKind(r.kind) ? `/ml/evaluations/${r.id}` : `/evaluations/${r.id}`}
                      className="text-xs text-accent hover:text-accent-bright transition-colors"
                    >
                      View →
                    </Link>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
      )}
    </div>
  )
}
