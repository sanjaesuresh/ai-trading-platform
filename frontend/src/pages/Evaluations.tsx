import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { listEvaluations } from '../api/evaluations'
import type { EvaluationSummary } from '../types/evaluation'
import { RunStatusBadge } from '../components/RunStatusBadge'
import { usePolling } from '../hooks/usePolling'
import { formatDate } from '../utils/format'
import { extractMessage } from '../utils/errors'

function isActive(status: string): boolean {
  return status === 'queued' || status === 'running'
}

function KindLabel({ kind }: { kind: string }) {
  const label = kind === 'walk_forward' ? 'Walk-forward' : 'Sweep'
  return <span className="text-zinc-300">{label}</span>
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
  const err = error
  const isLoading = loading && data === null

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-zinc-50">Evaluations</h1>
        <p className="text-sm text-zinc-500 mt-1">
          Parameter sweeps and out-of-sample walk-forward runs. Simulated only —
          not financial advice.
        </p>
      </div>

      {isLoading ? (
        <div
          className="bg-zinc-900 border border-zinc-800 rounded p-8 text-center motion-safe:animate-pulse"
          aria-busy="true"
        >
          <p className="text-sm text-zinc-500">Loading evaluations…</p>
        </div>
      ) : err ? (
        <div className="bg-zinc-900 border border-zinc-800 rounded p-5">
          <p role="alert" className="text-sm text-rose-400">
            {extractMessage(err)}
          </p>
        </div>
      ) : list.length === 0 ? (
        <div className="bg-zinc-900 border border-zinc-800 rounded p-8 text-center">
          <p className="text-sm text-zinc-500">
            No evaluations yet. Trigger a sweep or walk-forward via the API
            (POST /evaluations/sweep or /walk-forward).
          </p>
        </div>
      ) : (
        <div className="bg-zinc-900 border border-zinc-800 rounded overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-zinc-500 uppercase tracking-wider border-b border-zinc-800">
                <th className="px-4 py-2 font-medium">ID</th>
                <th className="px-4 py-2 font-medium">Kind</th>
                <th className="px-4 py-2 font-medium">Symbol</th>
                <th className="px-4 py-2 font-medium">Strategy</th>
                <th className="px-4 py-2 font-medium">Objective</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Created</th>
                <th className="px-4 py-2 font-medium" />
              </tr>
            </thead>
            <tbody>
              {list.map((r) => (
                <tr key={r.id} className="border-b border-zinc-800/60 last:border-0">
                  <td className="px-4 py-2 font-mono text-zinc-400">#{r.id}</td>
                  <td className="px-4 py-2">
                    <KindLabel kind={r.kind} />
                  </td>
                  <td className="px-4 py-2 text-zinc-50">{r.symbol}</td>
                  <td className="px-4 py-2 text-zinc-400">{r.strategy_name}</td>
                  <td className="px-4 py-2 font-mono text-zinc-400">{r.objective}</td>
                  <td className="px-4 py-2">
                    <RunStatusBadge status={r.status} />
                  </td>
                  <td className="px-4 py-2 text-zinc-500 font-mono text-xs">
                    {formatDate(r.created_at)}
                  </td>
                  <td className="px-4 py-2">
                    <Link
                      to={`/evaluations/${r.id}`}
                      className="text-amber-400 hover:text-amber-300 transition-colors"
                    >
                      View →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
