import { useParams, Link } from 'react-router-dom'
import { getEvaluation } from '../api/evaluations'
import type { EvaluationDetail } from '../types/evaluation'
import type { AblationResult, AblationArm } from '../types/news'
import { NewsDisclaimer } from '../components/NewsDisclaimer'
import { MLDisclaimer } from '../components/MLDisclaimer'
import { PageIntro, SectionHeader } from '../components/ui'
import { usePolling } from '../hooks/usePolling'
import { extractMessage } from '../utils/errors'

function isActive(status: string): boolean {
  return status === 'queued' || status === 'running'
}

function verdictClass(verdict: string): string {
  if (verdict === 'pass') return 'text-positive'
  if (verdict === 'fail') return 'text-negative'
  return 'text-caution'
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-surface border border-hairline rounded p-3">
      <p className="text-[11px] uppercase tracking-wide text-ink-subtle">{label}</p>
      <p className="text-lg font-mono text-ink mt-1">{value}</p>
    </div>
  )
}

function ArmCard({ title, arm }: { title: string; arm: AblationArm }) {
  const sig = arm.significance
  return (
    <div className="bg-surface border border-hairline rounded p-4 space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-ink">{title}</h3>
        <span className={`text-sm font-semibold uppercase ${verdictClass(arm.verdict)}`}>
          {arm.verdict}
        </span>
      </div>
      {sig && (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
          <dt className="text-ink-subtle">Sharpe</dt>
          <dd className="font-mono text-ink text-right">{sig.sharpe.toFixed(3)}</dd>
          <dt className="text-ink-subtle">Deflated Sharpe</dt>
          <dd className="font-mono text-ink text-right">{sig.deflated_sharpe.toFixed(3)}</dd>
          <dt className="text-ink-subtle">PBO</dt>
          <dd className="font-mono text-ink text-right">{sig.pbo.toFixed(3)}</dd>
          <dt className="text-ink-subtle">MC percentile</dt>
          <dd className="font-mono text-ink text-right">{sig.mc_percentile.toFixed(3)}</dd>
          <dt className="text-ink-subtle">Trials (N)</dt>
          <dd className="font-mono text-ink text-right">{sig.n_config_trials}</dd>
          <dt className="text-ink-subtle">OOS round trips</dt>
          <dd className="font-mono text-ink text-right">{sig.n_oos_round_trips}</dd>
        </dl>
      )}
    </div>
  )
}

export default function NewsAblationDetail() {
  const { id } = useParams<{ id: string }>()
  const runId = Number(id)
  const { data, error, loading } = usePolling<EvaluationDetail>(
    () => getEvaluation(runId),
    { active: true, intervalMs: 3000 },
  )

  const status = data?.status
  const abl =
    status === 'completed' ? (data?.results as unknown as AblationResult) : null

  return (
    <div className="space-y-6">
      <PageIntro title={`News ablation #${runId}`} icon="⚖️" eyebrow="News · Ablation">
        Price-only vs price-plus-news, over the same symbols, splits, and costs.
        The increment is tested on its own — deflated for the news search — and the
        LLM cost is charged to the news arm only.
      </PageIntro>

      <div className="grid grid-cols-1 gap-3">
        <NewsDisclaimer />
        <MLDisclaimer />
      </div>

      <p className="text-sm">
        <Link to="/news" className="text-accent hover:text-accent-bright">← Back to News</Link>
      </p>

      {loading && !data ? (
        <div className="bg-surface border border-hairline rounded p-8 text-center" aria-busy="true">
          <p className="text-sm text-ink-subtle">Loading ablation…</p>
        </div>
      ) : error ? (
        <div className="bg-surface border border-hairline rounded p-5">
          <p role="alert" className="text-sm text-negative">{extractMessage(error)}</p>
        </div>
      ) : data && isActive(status ?? '') ? (
        <div className="bg-surface border border-hairline rounded p-8 text-center motion-safe:animate-pulse">
          <p className="text-sm text-ink-subtle">
            Ablation is {status}… training both arms through the full significance
            battery. This can take a while.
          </p>
        </div>
      ) : data && status === 'failed' ? (
        <div className="bg-surface border border-hairline rounded p-5">
          <p role="alert" className="text-sm text-negative">
            Ablation failed: {(data as { error?: string | null }).error ?? 'unknown error'}
          </p>
        </div>
      ) : abl ? (
        <div className="space-y-6">
          <section aria-labelledby="verdict-heading">
            <SectionHeader
              id="verdict-heading"
              title="Does news add alpha, net of its cost?"
              subtitle="The paired incremental test on the per-bar (news − price) difference, deflated for the news search count."
            />
            <div
              className={`rounded border p-5 ${
                abl.incremental.beats_price_only
                  ? 'border-emerald-800 bg-emerald-950/40'
                  : 'border-hairline bg-surface'
              }`}
            >
              <p className={`text-xl font-semibold ${abl.incremental.beats_price_only ? 'text-positive' : 'text-caution'}`}>
                {abl.incremental.beats_price_only
                  ? 'News beats price-only (net of cost)'
                  : 'News does not add value net of cost — the expected outcome'}
              </p>
              <dl className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-4">
                <Stat label="Mean (news − price)" value={abl.incremental.mean_diff.toExponential(2)} />
                <Stat label="Bootstrap p-value" value={abl.incremental.bootstrap_p_value.toFixed(3)} />
                <Stat label="Deflated Sharpe (diff)" value={abl.incremental.deflated_sharpe.toFixed(3)} />
                <Stat label="Paired bars" value={String(abl.incremental.n_obs)} />
              </dl>
            </div>
          </section>

          <section aria-labelledby="arms-heading">
            <SectionHeader id="arms-heading" title="The two arms" subtitle={`Eval symbol: ${abl.eval_symbol}`} />
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <ArmCard title="Price-only" arm={abl.price_arm} />
              <ArmCard title="Price + news" arm={abl.news_arm} />
            </div>
          </section>

          <section aria-labelledby="cost-heading">
            <SectionHeader
              id="cost-heading"
              title="Cost & search accounting"
              subtitle="The news arm searched a larger space and pays its own LLM cost — both are charged before the verdict."
            />
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <Stat label="Price trials (N)" value={String(abl.price_n_trials)} />
              <Stat label="News trials (N)" value={String(abl.news_n_trials)} />
              <Stat label="Configs tried" value={String(abl.n_news_configs_tried)} />
              <Stat label="Billed LLM cost" value={`$${abl.annotation_cost_usd.toFixed(4)}`} />
              <Stat label="Daily cost drag" value={abl.daily_cost_drag.toExponential(2)} />
              <Stat
                label="Cost / news trade"
                value={Number.isFinite(abl.cost_per_news_trade) ? `$${abl.cost_per_news_trade.toFixed(4)}` : '—'}
              />
            </div>
            <p className="text-xs text-ink-subtle mt-3 leading-relaxed">{abl.dsr_caveat}</p>
          </section>
        </div>
      ) : (
        <div className="bg-surface border border-hairline rounded p-8 text-center">
          <p className="text-sm text-ink-subtle">No ablation result to show.</p>
        </div>
      )}
    </div>
  )
}
