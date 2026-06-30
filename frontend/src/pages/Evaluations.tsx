import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { listEvaluations } from '../api/evaluations'
import type { EvaluationSummary } from '../types/evaluation'
import { RunStatusBadge } from '../components/RunStatusBadge'
import { PageHeader, Table, Th, Td } from '../components/ui'
import { usePolling } from '../hooks/usePolling'
import { formatDate } from '../utils/format'
import { extractMessage } from '../utils/errors'

function isActive(status: string): boolean {
  return status === 'queued' || status === 'running'
}

function kindLabel(kind: string): string {
  return kind === 'walk_forward' ? 'Walk-forward' : 'Sweep'
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
      <PageHeader
        title="Evaluations"
        subtitle="Parameter sweeps (in-sample only) and walk-forward runs (out-of-sample, baseline-compared). Out-of-sample evidence is the only kind that counts. Simulated only — not financial advice."
        meta={
          list.length > 0 ? (
            <span className="font-mono text-sm text-zinc-500">
              {list.length} evaluation{list.length === 1 ? '' : 's'}
            </span>
          ) : undefined
        }
      />

      {isLoading ? (
        <div
          className="bg-zinc-900 border border-zinc-800 rounded p-8 text-center motion-safe:animate-pulse"
          aria-busy="true"
        >
          <p className="text-sm text-zinc-500">Loading evaluations…</p>
        </div>
      ) : error ? (
        <div className="bg-zinc-900 border border-zinc-800 rounded p-5">
          <p role="alert" className="text-sm text-rose-400">{extractMessage(error)}</p>
        </div>
      ) : list.length === 0 ? (
        <div className="bg-zinc-900 border border-zinc-800 rounded p-8 text-center">
          <p className="text-sm text-zinc-500">
            No evaluations yet. Trigger a sweep or walk-forward via the API
            (POST /evaluations/sweep or /walk-forward).
          </p>
        </div>
      ) : (
        <div className="bg-zinc-900 border border-zinc-800 rounded px-4 py-3">
          <Table>
            <thead>
              <tr className="border-b border-zinc-800">
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
            <tbody className="divide-y divide-zinc-800/60">
              {list.map((r) => (
                <tr key={r.id} className="hover:bg-zinc-800/30 transition-colors">
                  <Td mono className="text-zinc-500">#{r.id}</Td>
                  <Td className="text-zinc-300">{kindLabel(r.kind)}</Td>
                  <Td mono className="text-zinc-50">{r.symbol}</Td>
                  <Td className="text-zinc-400 text-xs">{r.strategy_name}</Td>
                  <Td mono className="text-zinc-400 text-xs">{r.objective}</Td>
                  <Td><RunStatusBadge status={r.status} /></Td>
                  <Td mono align="right" className="text-zinc-500">{formatDate(r.created_at)}</Td>
                  <Td align="right">
                    <Link
                      to={`/evaluations/${r.id}`}
                      className="text-xs text-amber-400 hover:text-amber-300 transition-colors"
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
