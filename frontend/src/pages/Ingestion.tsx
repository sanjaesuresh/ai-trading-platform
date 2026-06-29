import { useEffect, useState } from 'react'
import { listIngestionRuns, triggerIngestion } from '../api/ingestion'
import type { IngestionRunSummary } from '../types/ingestion'
import { RunStatusBadge } from '../components/RunStatusBadge'
import { usePolling } from '../hooks/usePolling'
import { formatDate } from '../utils/format'
import { extractMessage } from '../utils/errors'

function isActive(status: string): boolean {
  return status === 'queued' || status === 'running'
}

function rangeLabel(run: IngestionRunSummary): string {
  if (!run.range_start && !run.range_end) return '—'
  const start = run.range_start ? formatDate(run.range_start) : '?'
  const end = run.range_end ? formatDate(run.range_end) : '?'
  return `${start} → ${end}`
}

export default function Ingestion() {
  const [mode, setMode] = useState<'incremental' | 'backfill'>('incremental')
  const [symbolsText, setSymbolsText] = useState('')
  const [triggering, setTriggering] = useState(false)
  const [triggerMsg, setTriggerMsg] = useState<string | null>(null)
  const [triggerErr, setTriggerErr] = useState<string | null>(null)

  const [active, setActive] = useState(true)
  const { data, error, loading, refetch } = usePolling<IngestionRunSummary[]>(
    listIngestionRuns,
    { active, intervalMs: 2500 },
  )
  useEffect(() => {
    if (data) setActive(data.some((r) => isActive(r.status)))
  }, [data])

  const list = data ?? []

  const handleTrigger = async (e: React.FormEvent) => {
    e.preventDefault()
    setTriggerErr(null)
    setTriggerMsg(null)
    const symbols = symbolsText
      .split(',')
      .map((s) => s.trim().toUpperCase())
      .filter((s) => s.length > 0)
    setTriggering(true)
    try {
      const res = await triggerIngestion({
        mode,
        symbols: symbols.length > 0 ? symbols : null,
      })
      setTriggerMsg(`Queued ${mode} ingest (job ${res.job_id ?? 'n/a'}).`)
      setActive(true) // resume polling so the new rows are picked up
      refetch()
    } catch (err) {
      setTriggerErr(extractMessage(err))
    } finally {
      setTriggering(false)
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-xl font-semibold text-zinc-50">Data Ingestion</h1>
        <p className="text-sm text-zinc-500 mt-1">
          Trigger a market-data backfill or incremental update, and watch the audit
          trail. Simulated research tool — not financial advice.
        </p>
      </div>

      <section aria-labelledby="trigger-heading">
        <h2
          id="trigger-heading"
          className="text-xs font-medium text-zinc-500 uppercase tracking-wider mb-3"
        >
          Trigger a Run
        </h2>
        <form
          onSubmit={(e) => void handleTrigger(e)}
          className="bg-zinc-900 border border-zinc-800 rounded p-5 space-y-4"
        >
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label htmlFor="mode" className="block text-xs text-zinc-400 font-medium mb-1">
                Mode
              </label>
              <select
                id="mode"
                value={mode}
                onChange={(e) => setMode(e.target.value as 'incremental' | 'backfill')}
                className="w-full bg-zinc-950 border border-zinc-700 rounded px-2 py-1.5 text-sm font-mono text-zinc-50 focus:border-amber-400 focus:outline-none"
              >
                <option value="incremental">incremental (only new bars)</option>
                <option value="backfill">backfill (full history)</option>
              </select>
            </div>
            <div>
              <label htmlFor="symbols" className="block text-xs text-zinc-400 font-medium mb-1">
                Symbols (optional)
              </label>
              <input
                id="symbols"
                type="text"
                value={symbolsText}
                onChange={(e) => setSymbolsText(e.target.value)}
                placeholder="e.g. SPY, AAPL — empty = configured universe"
                className="w-full bg-zinc-950 border border-zinc-700 rounded px-2 py-1.5 text-sm font-mono text-zinc-50 focus:border-amber-400 focus:outline-none"
              />
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <button
              type="submit"
              disabled={triggering}
              aria-busy={triggering}
              className="inline-flex items-center gap-2 px-4 py-2 bg-amber-400 text-zinc-950 text-sm font-semibold rounded transition-colors hover:bg-amber-300 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {triggering ? 'Queuing…' : 'Run Ingestion'}
            </button>
            {triggerMsg && (
              <p role="status" className="text-sm text-emerald-400">
                {triggerMsg}
              </p>
            )}
          </div>
          {triggerErr !== null && (
            <p role="alert" className="text-sm text-rose-400">
              {triggerErr}
            </p>
          )}
        </form>
      </section>

      <section aria-labelledby="audit-heading">
        <h2
          id="audit-heading"
          className="text-xs font-medium text-zinc-500 uppercase tracking-wider mb-3"
        >
          Audit Trail
        </h2>
        {loading && data === null ? (
          <div className="bg-zinc-900 border border-zinc-800 rounded p-8 text-center motion-safe:animate-pulse" aria-busy="true">
            <p className="text-sm text-zinc-500">Loading ingestion history…</p>
          </div>
        ) : error ? (
          <div className="bg-zinc-900 border border-zinc-800 rounded p-5">
            <p role="alert" className="text-sm text-rose-400">
              {extractMessage(error)}
            </p>
          </div>
        ) : list.length === 0 ? (
          <div className="bg-zinc-900 border border-zinc-800 rounded p-8 text-center">
            <p className="text-sm text-zinc-500">
              No ingestion runs yet. Trigger one above.
            </p>
          </div>
        ) : (
          <div className="bg-zinc-900 border border-zinc-800 rounded overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-zinc-500 uppercase tracking-wider border-b border-zinc-800">
                  <th className="px-3 py-2 font-medium">ID</th>
                  <th className="px-3 py-2 font-medium">Provider</th>
                  <th className="px-3 py-2 font-medium">Symbol</th>
                  <th className="px-3 py-2 font-medium">Range</th>
                  <th className="px-3 py-2 font-medium">Fetched</th>
                  <th className="px-3 py-2 font-medium">Written</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium">Created</th>
                </tr>
              </thead>
              <tbody>
                {list.map((r) => (
                  <tr key={r.id} className="border-b border-zinc-800/60 last:border-0 align-top">
                    <td className="px-3 py-2 font-mono text-zinc-400">#{r.id}</td>
                    <td className="px-3 py-2 text-zinc-400">{r.provider}</td>
                    <td className="px-3 py-2 text-zinc-50">{r.symbol}</td>
                    <td className="px-3 py-2 font-mono text-xs text-zinc-500">{rangeLabel(r)}</td>
                    <td className="px-3 py-2 font-mono text-zinc-400">{r.rows_fetched ?? '—'}</td>
                    <td className="px-3 py-2 font-mono text-zinc-400">{r.rows_written ?? '—'}</td>
                    <td className="px-3 py-2">
                      <RunStatusBadge status={r.status} />
                      {r.error && (
                        <p className="text-xs text-rose-400 mt-1 max-w-xs" title={r.error}>
                          {r.error}
                        </p>
                      )}
                    </td>
                    <td className="px-3 py-2 font-mono text-xs text-zinc-500">
                      {formatDate(r.created_at)}
                    </td>
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
