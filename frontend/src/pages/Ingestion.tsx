import { useEffect, useState } from 'react'
import { listIngestionRuns, triggerIngestion } from '../api/ingestion'
import type { IngestionRunSummary } from '../types/ingestion'
import { RunStatusBadge } from '../components/RunStatusBadge'
import { PageIntro, SectionHeader, Field, inputClass, Table, Th, Td, Term } from '../components/ui'
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

function durationLabel(run: IngestionRunSummary): string {
  if (!run.finished_at) return isActive(run.status) ? '…' : '—'
  const ms = new Date(run.finished_at).getTime() - new Date(run.created_at).getTime()
  if (ms < 1000) return `${ms}ms`
  const s = ms / 1000
  if (s < 60) return `${s.toFixed(1)}s`
  return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`
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
      <PageIntro title="Get price data" icon="📥" eyebrow="Data">
        Strategies need history to run on. Here you pull price data for the symbols
        you care about — a <Term id="backfill">backfill</Term> grabs a long stretch
        of history at once, while an incremental update just adds the newest days.
        Every <Term id="ingestion">fetch</Term> is quality-checked and logged in the
        table below. Simulated research tool — not financial advice.
      </PageIntro>

      <section aria-labelledby="trigger-heading">
        <SectionHeader
          id="trigger-heading"
          title="Trigger a Run"
          subtitle="Backfill pulls full history; incremental adds only bars newer than what's stored."
        />
        <form
          onSubmit={(e) => void handleTrigger(e)}
          className="bg-surface border border-hairline rounded p-5 space-y-4"
        >
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Field
              label="Mode"
              htmlFor="mode"
              hint="Backfill is a full re-pull; incremental is a fast top-up."
            >
              <select
                id="mode"
                value={mode}
                onChange={(e) => setMode(e.target.value as 'incremental' | 'backfill')}
                className={inputClass}
              >
                <option value="incremental">incremental (only new bars)</option>
                <option value="backfill">backfill (full history)</option>
              </select>
            </Field>
            <Field
              label="Symbols"
              htmlFor="symbols"
              unit="optional"
              hint="Comma-separated. Leave empty to use the configured universe."
            >
              <input
                id="symbols"
                type="text"
                value={symbolsText}
                onChange={(e) => setSymbolsText(e.target.value)}
                placeholder="e.g. SPY, AAPL"
                className={inputClass}
              />
            </Field>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <button
              type="submit"
              disabled={triggering}
              aria-busy={triggering}
              className="inline-flex items-center gap-2 px-4 py-2 bg-accent text-canvas text-sm font-semibold rounded transition-colors hover:bg-accent-bright disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {triggering ? 'Queuing…' : 'Run Ingestion'}
            </button>
            {triggerMsg && (
              <p role="status" className="text-sm text-positive">{triggerMsg}</p>
            )}
          </div>
          {triggerErr !== null && (
            <p role="alert" className="text-sm text-negative">{triggerErr}</p>
          )}
        </form>
      </section>

      <section aria-labelledby="audit-heading">
        <SectionHeader
          id="audit-heading"
          title="Audit Trail"
          subtitle="Every ingest, newest first — rows fetched from the provider vs. rows actually written after de-duplication and quality checks."
          right={
            list.length > 0 ? (
              <span className="font-mono text-xs text-ink-subtle">{list.length} runs</span>
            ) : undefined
          }
        />
        {loading && data === null ? (
          <div className="bg-surface border border-hairline rounded p-8 text-center motion-safe:animate-pulse" aria-busy="true">
            <p className="text-sm text-ink-subtle">Loading ingestion history…</p>
          </div>
        ) : error ? (
          <div className="bg-surface border border-hairline rounded p-5">
            <p role="alert" className="text-sm text-negative">{extractMessage(error)}</p>
          </div>
        ) : list.length === 0 ? (
          <div className="bg-surface border border-hairline rounded p-8 text-center">
            <p className="text-sm text-ink-subtle">No ingestion runs yet. Trigger one above.</p>
          </div>
        ) : (
          <div className="bg-surface border border-hairline rounded px-4 py-3">
            <Table>
              <thead>
                <tr className="border-b border-hairline">
                  <Th>ID</Th>
                  <Th>Provider</Th>
                  <Th>Symbol</Th>
                  <Th>Range</Th>
                  <Th align="right" sub="rows">Fetched</Th>
                  <Th align="right" sub="rows">Written</Th>
                  <Th align="right">Duration</Th>
                  <Th>Status</Th>
                  <Th align="right">Created</Th>
                </tr>
              </thead>
              <tbody className="divide-y divide-hairline/60">
                {list.map((r) => (
                  <tr key={r.id} className="align-top hover:bg-raised/30 transition-colors">
                    <Td mono className="text-ink-muted">#{r.id}</Td>
                    <Td className="text-ink-muted">{r.provider}</Td>
                    <Td mono className="text-ink">{r.symbol}</Td>
                    <Td mono className="text-ink-subtle">{rangeLabel(r)}</Td>
                    <Td mono align="right" className="text-ink-muted">{r.rows_fetched ?? '—'}</Td>
                    <Td mono align="right" className="text-ink">{r.rows_written ?? '—'}</Td>
                    <Td mono align="right" className="text-ink-subtle">{durationLabel(r)}</Td>
                    <Td>
                      <RunStatusBadge status={r.status} />
                      {r.error && (
                        <p className="text-xs text-negative mt-1 max-w-xs" title={r.error}>
                          {r.error}
                        </p>
                      )}
                    </Td>
                    <Td mono align="right" className="text-ink-subtle">{formatDate(r.created_at)}</Td>
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
