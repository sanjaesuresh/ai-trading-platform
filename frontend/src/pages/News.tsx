import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  getNewsAnnotationSummary,
  listNewsIngestionRuns,
  triggerNewsAnnotate,
  triggerNewsIngest,
  triggerNewsAblation,
} from '../api/news'
import type { NewsAnnotationSummary, NewsIngestionRunSummary } from '../types/news'
import { NewsDisclaimer } from '../components/NewsDisclaimer'
import { RunStatusBadge } from '../components/RunStatusBadge'
import { PageIntro, SectionHeader, Field, inputClass, Table, Th, Td } from '../components/ui'
import { usePolling } from '../hooks/usePolling'
import { formatDate } from '../utils/format'
import { extractMessage } from '../utils/errors'

function isActive(status: string): boolean {
  return status === 'queued' || status === 'running'
}

function parseSymbols(text: string): string[] {
  return text
    .split(',')
    .map((s) => s.trim().toUpperCase())
    .filter((s) => s.length > 0)
}

export default function News() {
  const navigate = useNavigate()
  const [active, setActive] = useState(true)
  const { data, error, loading, refetch } = usePolling<NewsIngestionRunSummary[]>(
    listNewsIngestionRuns,
    { active, intervalMs: 2500 },
  )
  const summary = usePolling<NewsAnnotationSummary>(getNewsAnnotationSummary, {
    active,
    intervalMs: 5000,
  })
  useEffect(() => {
    if (data) setActive(data.some((r) => isActive(r.status)))
  }, [data])

  const list = data ?? []

  const [ingestMode, setIngestMode] = useState<'incremental' | 'backfill'>('incremental')
  const [ingestSymbols, setIngestSymbols] = useState('')
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const [ablSymbols, setAblSymbols] = useState('SPY, AAPL')
  const [ablEval, setAblEval] = useState('SPY')
  const [ablConfigs, setAblConfigs] = useState(1)

  const wrap = async (fn: () => Promise<string>) => {
    setErr(null)
    setMsg(null)
    setBusy(true)
    try {
      setMsg(await fn())
      setActive(true)
      refetch()
    } catch (e) {
      setErr(extractMessage(e))
    } finally {
      setBusy(false)
    }
  }

  const onIngest = () =>
    void wrap(async () => {
      const symbols = parseSymbols(ingestSymbols)
      const res = await triggerNewsIngest({
        mode: ingestMode,
        symbols: symbols.length ? symbols : null,
      })
      return `Queued news ${ingestMode} ingest (job ${res.job_id ?? 'n/a'}).`
    })

  const onAnnotate = (phase: 'submit' | 'collect' | 'both') =>
    void wrap(async () => {
      const res = await triggerNewsAnnotate({ phase })
      return `Queued annotate (${phase}, job ${res.job_id ?? 'n/a'}).`
    })

  const onAblation = () =>
    void wrap(async () => {
      const symbols = parseSymbols(ablSymbols)
      const res = await triggerNewsAblation({
        symbols,
        eval_symbol: ablEval.trim().toUpperCase(),
        n_news_configs_tried: ablConfigs,
      })
      navigate(`/news/ablation/${res.evaluation_run_id}`)
      return `Queued ablation (run #${res.evaluation_run_id}).`
    })

  const s = summary.data

  return (
    <div className="space-y-8">
      <PageIntro title="News & LLM signals" icon="📰" eyebrow="News">
        Ingest news, label it with an LLM (sentiment + event type), and ask the
        honest question: does news add anything to a price-only model once you
        charge what it cost to produce? Simulated research tool — not advice.
      </PageIntro>

      <NewsDisclaimer />

      <section aria-labelledby="annot-heading">
        <SectionHeader
          id="annot-heading"
          title="Annotation coverage & cost"
          subtitle="Honest billed spend under the live prompt version — the cost the ablation charges the news arm."
        />
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
          {[
            ['Prompt', s ? s.prompt_version : '—'],
            ['Annotated', s ? String(s.total_annotations) : '—'],
            ['Failed', s ? String(s.failed_annotations) : '—'],
            ['Pending', s ? String(s.pending_articles) : '—'],
            ['Billed cost', s ? `$${s.total_cost_usd.toFixed(4)}` : '—'],
          ].map(([label, value]) => (
            <div key={label} className="bg-surface border border-hairline rounded p-3">
              <p className="text-[11px] uppercase tracking-wide text-ink-subtle">{label}</p>
              <p className="text-lg font-mono text-ink mt-1">{value}</p>
            </div>
          ))}
        </div>
      </section>

      <section aria-labelledby="trigger-heading">
        <SectionHeader
          id="trigger-heading"
          title="Run news jobs"
          subtitle="Ingest fetches + quality-gates news; annotate runs the LLM (submit then collect); the ablation compares price-only vs price-plus-news net of cost."
        />
        <div className="bg-surface border border-hairline rounded p-5 space-y-6">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <Field label="Ingest mode" htmlFor="ingest-mode">
              <select
                id="ingest-mode"
                value={ingestMode}
                onChange={(e) => setIngestMode(e.target.value as 'incremental' | 'backfill')}
                className={inputClass}
              >
                <option value="incremental">incremental (only new items)</option>
                <option value="backfill">backfill (full history)</option>
              </select>
            </Field>
            <Field label="Symbols" htmlFor="ingest-symbols" unit="optional">
              <input
                id="ingest-symbols"
                type="text"
                value={ingestSymbols}
                onChange={(e) => setIngestSymbols(e.target.value)}
                placeholder="e.g. SPY, AAPL"
                className={inputClass}
              />
            </Field>
            <div className="flex items-end">
              <button
                type="button"
                onClick={onIngest}
                disabled={busy}
                className="px-4 py-2 bg-accent text-canvas text-sm font-semibold rounded hover:bg-accent-bright disabled:opacity-50"
              >
                Ingest news
              </button>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3 border-t border-hairline pt-4">
            <span className="text-sm text-ink-muted">Annotate (LLM):</span>
            <button type="button" onClick={() => onAnnotate('submit')} disabled={busy}
              className="px-3 py-1.5 text-sm rounded border border-hairline hover:bg-raised/40 disabled:opacity-50">Submit</button>
            <button type="button" onClick={() => onAnnotate('collect')} disabled={busy}
              className="px-3 py-1.5 text-sm rounded border border-hairline hover:bg-raised/40 disabled:opacity-50">Collect</button>
            <span className="text-xs text-ink-subtle">Batch API is two-phase; submit parks a batch, collect retrieves it.</span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-4 gap-4 border-t border-hairline pt-4">
            <Field label="Ablation symbols" htmlFor="abl-symbols">
              <input id="abl-symbols" type="text" value={ablSymbols}
                onChange={(e) => setAblSymbols(e.target.value)} className={inputClass} />
            </Field>
            <Field label="Eval symbol" htmlFor="abl-eval">
              <input id="abl-eval" type="text" value={ablEval}
                onChange={(e) => setAblEval(e.target.value)} className={inputClass} />
            </Field>
            <Field label="News configs tried" htmlFor="abl-configs"
              hint="Multiplies the news arm's deflated-Sharpe trial count.">
              <input id="abl-configs" type="number" min={1} value={ablConfigs}
                onChange={(e) => setAblConfigs(Math.max(1, Number(e.target.value)))} className={inputClass} />
            </Field>
            <div className="flex items-end">
              <button type="button" onClick={onAblation} disabled={busy}
                className="px-4 py-2 bg-accent text-canvas text-sm font-semibold rounded hover:bg-accent-bright disabled:opacity-50">
                Run ablation
              </button>
            </div>
          </div>

          {msg && <p role="status" className="text-sm text-positive">{msg}</p>}
          {err && <p role="alert" className="text-sm text-negative">{err}</p>}
        </div>
      </section>

      <section aria-labelledby="audit-heading">
        <SectionHeader
          id="audit-heading"
          title="Ingestion audit trail"
          subtitle="Every news ingest, newest first — items fetched vs. written after de-duplication and the news quality gate."
          right={list.length > 0 ? (
            <span className="font-mono text-xs text-ink-subtle">{list.length} runs</span>
          ) : undefined}
        />
        {loading && data === null ? (
          <div className="bg-surface border border-hairline rounded p-8 text-center" aria-busy="true">
            <p className="text-sm text-ink-subtle">Loading news history…</p>
          </div>
        ) : error ? (
          <div className="bg-surface border border-hairline rounded p-5">
            <p role="alert" className="text-sm text-negative">{extractMessage(error)}</p>
          </div>
        ) : list.length === 0 ? (
          <div className="bg-surface border border-hairline rounded p-8 text-center">
            <p className="text-sm text-ink-subtle">No news ingested yet. Trigger an ingest above.</p>
          </div>
        ) : (
          <div className="bg-surface border border-hairline rounded px-4 py-3">
            <Table>
              <thead>
                <tr className="border-b border-hairline">
                  <Th>ID</Th>
                  <Th>Provider</Th>
                  <Th>Symbol</Th>
                  <Th align="right" sub="items">Fetched</Th>
                  <Th align="right" sub="items">Written</Th>
                  <Th align="right" sub="items">Dropped</Th>
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
                    <Td mono align="right" className="text-ink-muted">{r.items_fetched ?? '—'}</Td>
                    <Td mono align="right" className="text-ink">{r.items_written ?? '—'}</Td>
                    <Td mono align="right" className="text-ink-subtle">{r.items_dropped ?? '—'}</Td>
                    <Td>
                      <RunStatusBadge status={r.status} />
                      {r.error && (
                        <p className="text-xs text-negative mt-1 max-w-xs" title={r.error}>{r.error}</p>
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
