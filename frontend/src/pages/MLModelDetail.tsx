import { useParams } from 'react-router-dom'
import { getMLModel } from '../api/ml'
import type { MLModelDetail as MLModelDetailType } from '../types/ml'
import { MLDisclaimer } from '../components/MLDisclaimer'
import {
  PageHeader,
  ProvenanceStrip,
  SectionHeader,
  Stat,
  StatGrid,
} from '../components/ui'
import type { ProvenanceItem } from '../components/ui'
import { usePolling } from '../hooks/usePolling'
import { formatDate } from '../utils/format'
import { extractMessage, isNotFound } from '../utils/errors'

function fmt(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'boolean') return v ? 'Yes' : 'No'
  if (typeof v === 'number') return Number.isFinite(v) ? v.toFixed(4) : '—'
  return String(v)
}

function ValidationMetrics({ metrics }: { metrics: Record<string, unknown> }) {
  const entries = Object.entries(metrics)
  if (entries.length === 0) {
    return (
      <p className="text-sm text-zinc-500">
        No validation metrics recorded for this model.
      </p>
    )
  }
  return (
    <StatGrid cols="grid-cols-2 md:grid-cols-3 lg:grid-cols-4">
      {entries.map(([k, v]) => (
        <Stat
          key={k}
          label={k.replace(/_/g, ' ')}
          value={fmt(v)}
          hint={`Validation: ${k}`}
        />
      ))}
    </StatGrid>
  )
}

function JsonBlock({ label, data }: { label: string; data: Record<string, unknown> }) {
  const entries = Object.entries(data)
  if (entries.length === 0) return null
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded p-4">
      <p className="text-[11px] font-medium text-zinc-500 uppercase tracking-wider mb-2">
        {label}
      </p>
      <dl className="space-y-1">
        {entries.map(([k, v]) => (
          <div key={k} className="flex gap-3">
            <dt className="font-mono text-xs text-zinc-500 shrink-0 w-40 truncate">
              {k}
            </dt>
            <dd className="font-mono text-xs text-zinc-300 break-all">
              {JSON.stringify(v)}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

export default function MLModelDetail() {
  const { id: modelId } = useParams<{ id: string }>()

  const { data, error, loading } = usePolling<MLModelDetailType>(
    () => getMLModel(modelId ?? ''),
    { active: false },
  )

  const provenance: ProvenanceItem[] = data
    ? [
        { label: 'Model ID', value: data.model_id },
        { label: 'Feature Spec', value: data.feature_spec_version },
        { label: 'Symbols', value: data.symbols.join(', ') },
        {
          label: 'Train Window',
          value: `${data.train_start.slice(0, 10)} – ${data.train_end.slice(0, 10)}`,
        },
        { label: 'Registered', value: formatDate(data.created_at) },
        {
          label: 'Code Dirty',
          value: data.code_dirty ? 'Yes (uncommitted changes)' : 'No',
        },
      ]
    : []

  return (
    <div className="space-y-6">
      {loading && data === null ? (
        <div
          className="bg-zinc-900 border border-zinc-800 rounded p-8 text-center motion-safe:animate-pulse"
          aria-busy="true"
        >
          <p className="text-sm text-zinc-500">Loading model…</p>
        </div>
      ) : error ? (
        <div className="space-y-3">
          <div className="bg-zinc-900 border border-zinc-800 rounded p-5">
            <p role="alert" className="text-sm text-rose-400">
              {isNotFound(error)
                ? `Model "${modelId}" not found.`
                : extractMessage(error)}
            </p>
          </div>
        </div>
      ) : data ? (
        <>
          <PageHeader
            back={{ to: '/ml', label: 'ML Models' }}
            title={
              <span className="font-mono">{data.model_id}</span>
            }
            subtitle={`LightGBM classifier · ${data.symbols.join(', ')} · horizon ${data.horizon}d`}
          />

          <MLDisclaimer />

          <ProvenanceStrip items={provenance} />

          {/* Provenance hashes */}
          <section aria-labelledby="prov-heading" className="space-y-3">
            <SectionHeader
              id="prov-heading"
              title="Artifact Provenance"
              subtitle="Hashes that tie this model to the exact code and data it was trained on. A dirty code hash means uncommitted changes were present — treat with caution."
            />
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <Stat
                label="Code Git Hash"
                value={data.code_git_hash.slice(0, 12)}
                hint={`Full: ${data.code_git_hash}${data.code_dirty ? ' — DIRTY (uncommitted changes)' : ''}`}
                tone={data.code_dirty ? 'neg' : 'default'}
              />
              <Stat
                label="Artifact Hash"
                value={data.artifact_hash.slice(0, 12)}
                hint={`Full: ${data.artifact_hash}`}
              />
              {data.code_diff_hash && (
                <Stat
                  label="Diff Hash"
                  value={data.code_diff_hash.slice(0, 12)}
                  hint="Hash of uncommitted diff at training time."
                  tone="neg"
                />
              )}
            </div>
          </section>

          {/* Core config */}
          <section aria-labelledby="config-heading" className="space-y-3">
            <SectionHeader
              id="config-heading"
              title="Training Config"
              subtitle="Parameters used to train and calibrate this model."
            />
            <StatGrid cols="grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
              <Stat label="Horizon" value={String(data.horizon)} unit="bars" hint="Forecast look-ahead." />
              <Stat label="Deadband" value={data.deadband.toFixed(3)} hint="Neutral label fraction." />
              <Stat label="Calibration" value={data.calibration} mono={false} hint="Probability calibration method." />
              <Stat label="Calibrated" value={data.calibrated ? 'Yes' : 'No'} mono={false} hint="Whether calibration was applied." tone={data.calibrated ? 'pos' : 'default'} />
              <Stat label="Min Hold" value={String(data.min_hold)} unit="bars" hint="Minimum holding period." />
              <Stat label="Enter θ" value={data.enter_threshold.toFixed(3)} hint="Probability threshold to enter a position." />
              <Stat label="Exit θ" value={data.exit_threshold.toFixed(3)} hint="Probability threshold to exit a position." />
              <Stat label="Seed" value={String(data.seed)} hint="Random seed for reproducibility." />
              <Stat label="n_fit" value={String(data.n_fit)} hint="Training-set rows." />
              <Stat label="n_calib" value={String(data.n_calib)} hint="Calibration-set rows." />
              <Stat label="n_thresh" value={String(data.n_thresh)} hint="Threshold-search rows." />
              <Stat label="Eff. N" value={data.effective_n.toFixed(1)} hint="Uniqueness-adjusted effective sample size." />
            </StatGrid>
          </section>

          {/* Validation metrics */}
          <section aria-labelledby="val-heading" className="space-y-3">
            <SectionHeader
              id="val-heading"
              title="Validation Metrics"
              subtitle="In-sample validation diagnostics recorded at training time. These are NOT out-of-sample evidence — do not interpret them as performance."
            />
            <div role="note" className="bg-amber-950/30 border border-amber-900/40 rounded p-3">
              <p className="text-xs text-amber-300/70">
                Validation metrics are in-sample diagnostics, not out-of-sample
                performance. Run a walk-forward evaluation for a meaningful result.
              </p>
            </div>
            <ValidationMetrics
              metrics={data.validation_metrics as Record<string, unknown>}
            />
          </section>

          {/* LightGBM params */}
          {Object.keys(data.lgbm_params).length > 0 && (
            <section aria-labelledby="lgbm-heading" className="space-y-3">
              <SectionHeader
                id="lgbm-heading"
                title="LightGBM Hyperparameters"
                subtitle="Parameters passed to LightGBM at training time."
              />
              <JsonBlock label="lgbm_params" data={data.lgbm_params} />
            </section>
          )}

          {/* Selection config */}
          {Object.keys(data.selection_config).length > 0 && (
            <section aria-labelledby="sel-heading" className="space-y-3">
              <SectionHeader
                id="sel-heading"
                title="Threshold Selection Config"
                subtitle="Grid search parameters used to select the enter/exit thresholds."
              />
              <JsonBlock label="selection_config" data={data.selection_config} />
            </section>
          )}
        </>
      ) : null}
    </div>
  )
}
