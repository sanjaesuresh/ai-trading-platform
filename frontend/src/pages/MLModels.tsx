import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { listMLModels, runMLWalkForward } from '../api/ml'
import type { MLModelSummary } from '../types/ml'
import { MLDisclaimer } from '../components/MLDisclaimer'
import {
  Field,
  inputClass,
  PageIntro,
  Term,
  ProvenanceStrip,
  SectionHeader,
  Table,
  Td,
  Th,
} from '../components/ui'
import type { ProvenanceItem } from '../components/ui'
import { usePolling } from '../hooks/usePolling'
import { formatDate } from '../utils/format'
import { extractMessage } from '../utils/errors'

// ---------------------------------------------------------------------------
// Models table
// ---------------------------------------------------------------------------

function ModelsTable({ models }: { models: MLModelSummary[] }) {
  if (models.length === 0) {
    return (
      <div className="bg-surface border border-hairline rounded p-8 text-center">
        <p className="text-sm text-ink-subtle">
          No ML models registered yet. Train one via{' '}
          <code className="font-mono text-xs text-ink-muted">
            POST /ml/models
          </code>{' '}
          or use the launcher below to start a walk-forward evaluation (which
          trains a fresh model per split internally).
        </p>
      </div>
    )
  }

  return (
    <div className="bg-surface border border-hairline rounded px-4 py-3">
      <Table>
        <thead>
          <tr className="border-b border-hairline">
            <Th>Model ID</Th>
            <Th>Feature Spec</Th>
            <Th>Symbols</Th>
            <Th>Train Window</Th>
            <Th align="right">Horizon</Th>
            <Th align="right">Enter θ</Th>
            <Th align="right">Calibrated</Th>
            <Th align="right">Registered</Th>
            <Th align="right">
              <span className="sr-only">View</span>
            </Th>
          </tr>
        </thead>
        <tbody className="divide-y divide-hairline/60">
          {models.map((m) => (
            <tr
              key={m.id}
              className="hover:bg-raised/30 transition-colors"
            >
              <Td mono className="text-ink max-w-[12rem] truncate">
                {m.model_id}
              </Td>
              <Td mono className="text-ink-subtle text-xs">
                {m.feature_spec_version}
              </Td>
              <Td mono className="text-ink-muted text-xs">
                {m.symbols.join(', ')}
              </Td>
              <Td mono className="text-ink-subtle text-xs">
                {m.train_start.slice(0, 10)}–{m.train_end.slice(0, 10)}
              </Td>
              <Td mono align="right" className="text-ink-muted">
                {m.horizon}d
              </Td>
              <Td mono align="right" className="text-ink-muted">
                {m.enter_threshold.toFixed(2)}
              </Td>
              <Td mono align="right" className="text-ink-muted">
                {m.calibrated ? 'Yes' : 'No'}
              </Td>
              <Td mono align="right" className="text-ink-subtle">
                {formatDate(m.created_at)}
              </Td>
              <Td align="right">
                <Link
                  to={`/ml/models/${encodeURIComponent(m.model_id)}`}
                  className="text-xs text-accent hover:text-accent-bright transition-colors"
                >
                  Detail →
                </Link>
              </Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Walk-forward launcher
// ---------------------------------------------------------------------------

const DEFAULT_SYMBOLS = 'SPY'
const SCHEME_OPTIONS: Array<{ value: 'anchored' | 'rolling'; label: string }> =
  [
    { value: 'anchored', label: 'Anchored (expanding window)' },
    { value: 'rolling', label: 'Rolling (fixed window)' },
  ]

function WalkForwardLauncher() {
  const navigate = useNavigate()

  const [symbolsText, setSymbolsText] = useState(DEFAULT_SYMBOLS)
  const [evalSymbol, setEvalSymbol] = useState('SPY')
  const [scheme, setScheme] = useState<'anchored' | 'rolling'>('anchored')
  const [inSampleDates, setInSampleDates] = useState('504')
  const [outSampleDates, setOutSampleDates] = useState('126')
  const [stepDates, setStepDates] = useState('126')
  const [horizon, setHorizon] = useState('5')
  const [feeBps, setFeeBps] = useState('5')
  const [slippageBps, setSlippageBps] = useState('5')
  const [submitting, setSubmitting] = useState(false)
  const [formErr, setFormErr] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setFormErr(null)

    const symbols = symbolsText
      .split(',')
      .map((s) => s.trim())
      .filter((s) => s.length > 0)

    if (symbols.length === 0) {
      setFormErr('Enter at least one symbol.')
      return
    }
    if (!evalSymbol.trim()) {
      setFormErr('Evaluation symbol is required.')
      return
    }
    if (!symbols.includes(evalSymbol.trim())) {
      setFormErr(
        `Eval symbol "${evalSymbol.trim()}" must appear in the symbols list.`,
      )
      return
    }

    const outSample = parseInt(outSampleDates, 10) || 126
    const step = parseInt(stepDates, 10) || 126
    if (step < outSample) {
      setFormErr(
        `Step bars (${step}) must be ≥ OOS bars (${outSample}) to avoid overlapping test windows.`,
      )
      return
    }

    setSubmitting(true)
    try {
      const result = await runMLWalkForward({
        symbols,
        eval_symbol: evalSymbol.trim(),
        scheme,
        in_sample_dates: parseInt(inSampleDates, 10) || 504,
        out_sample_dates: parseInt(outSampleDates, 10) || 126,
        step_dates: parseInt(stepDates, 10) || 126,
        horizon: parseInt(horizon, 10) || 5,
        fee_bps: parseFloat(feeBps) || 5,
        slippage_bps: parseFloat(slippageBps) || 5,
      })
      navigate(`/ml/evaluations/${result.id}`)
    } catch (err) {
      setFormErr(extractMessage(err))
      setSubmitting(false)
    }
  }

  return (
    <section aria-labelledby="launcher-heading" className="space-y-4">
      <SectionHeader
        id="launcher-heading"
        title="Run Walk-Forward Evaluation"
        subtitle="Train a fresh model per purged split and score it out-of-sample against buy-and-hold, rule, and logistic baselines, plus a Monte-Carlo ensemble. Results are simulated — not financial advice."
      />

      <form
        onSubmit={(e) => { void handleSubmit(e) }}
        className="bg-surface border border-hairline rounded p-5 space-y-4"
        noValidate
      >
        {/* Symbol inputs */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Field
            label="Training Symbols"
            htmlFor="wf-symbols"
            hint="Comma-separated tickers. All must exist in the DB."
          >
            <input
              id="wf-symbols"
              type="text"
              className={inputClass}
              value={symbolsText}
              onChange={(e) => setSymbolsText(e.target.value)}
              placeholder="SPY, AAPL, MSFT"
              autoComplete="off"
              required
              aria-required="true"
            />
          </Field>
          <Field
            label="Eval Symbol"
            htmlFor="wf-eval-symbol"
            hint="Single symbol scored OOS. Must be in the training pool."
          >
            <input
              id="wf-eval-symbol"
              type="text"
              className={inputClass}
              value={evalSymbol}
              onChange={(e) => setEvalSymbol(e.target.value)}
              placeholder="SPY"
              autoComplete="off"
              required
              aria-required="true"
            />
          </Field>
        </div>

        {/* Window config */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <Field
            label="In-Sample Bars"
            htmlFor="wf-in-sample"
            hint="Default 504 (~2 years)"
          >
            <input
              id="wf-in-sample"
              type="number"
              min={2}
              className={inputClass}
              value={inSampleDates}
              onChange={(e) => setInSampleDates(e.target.value)}
            />
          </Field>
          <Field
            label="OOS Bars"
            htmlFor="wf-out-sample"
            hint="Default 126 (~6 months)"
          >
            <input
              id="wf-out-sample"
              type="number"
              min={2}
              className={inputClass}
              value={outSampleDates}
              onChange={(e) => setOutSampleDates(e.target.value)}
            />
          </Field>
          <Field
            label="Step Bars"
            htmlFor="wf-step"
            hint="Must be ≥ OOS bars"
          >
            <input
              id="wf-step"
              type="number"
              min={1}
              className={inputClass}
              value={stepDates}
              onChange={(e) => setStepDates(e.target.value)}
            />
          </Field>
          <Field
            label="Forecast Horizon"
            htmlFor="wf-horizon"
            unit="bars"
            hint="Label look-ahead in bars"
          >
            <input
              id="wf-horizon"
              type="number"
              min={1}
              className={inputClass}
              value={horizon}
              onChange={(e) => setHorizon(e.target.value)}
            />
          </Field>
        </div>

        {/* Costs and scheme */}
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
          <Field label="Fee" htmlFor="wf-fee" unit="bps">
            <input
              id="wf-fee"
              type="number"
              min={0}
              step={0.5}
              className={inputClass}
              value={feeBps}
              onChange={(e) => setFeeBps(e.target.value)}
            />
          </Field>
          <Field label="Slippage" htmlFor="wf-slippage" unit="bps">
            <input
              id="wf-slippage"
              type="number"
              min={0}
              step={0.5}
              className={inputClass}
              value={slippageBps}
              onChange={(e) => setSlippageBps(e.target.value)}
            />
          </Field>
          <Field label="Scheme" htmlFor="wf-scheme">
            <select
              id="wf-scheme"
              className={inputClass}
              value={scheme}
              onChange={(e) =>
                setScheme(e.target.value as 'anchored' | 'rolling')
              }
            >
              {SCHEME_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </Field>
        </div>

        {formErr && (
          <p role="alert" className="text-sm text-negative">
            {formErr}
          </p>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="inline-flex items-center gap-2 bg-accent hover:bg-accent-bright disabled:bg-raised disabled:text-ink-subtle text-canvas text-sm font-semibold px-4 py-2 rounded transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          {submitting ? 'Enqueuing…' : 'Run Walk-Forward'}
        </button>
      </form>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function MLModels() {
  // Fetch once on mount; model list is static — no polling needed.
  const { data, error, loading } = usePolling<MLModelSummary[]>(
    listMLModels,
    { active: false },
  )

  const models = data ?? []
  const isLoading = loading && data === null

  const provenance: ProvenanceItem[] = [
    {
      label: 'Models',
      value: isLoading ? '…' : String(models.length),
    },
    { label: 'Engine', value: 'LightGBM + logistic floor' },
    { label: 'Data', value: 'Simulated (DB)' },
  ]

  return (
    <div className="space-y-6">
      <PageIntro
        title="Machine-learning models"
        icon="🤖"
        eyebrow="ML"
        meta={
          !isLoading && models.length > 0 ? (
            <span className="font-mono text-sm text-ink-subtle">
              {models.length} model{models.length === 1 ? '' : 's'}
            </span>
          ) : undefined
        }
      >
        These are experimental models that try to learn patterns from history,
        rather than following hand-written rules. Each one is trained on a past
        window, <Term id="calibration">calibrated</Term> so its confidence is
        meaningful, and pinned to an exact version so results can be reproduced.
        Treat them as research, not predictions — all results are simulated and not
        financial advice.
      </PageIntro>

      <MLDisclaimer />

      <ProvenanceStrip items={provenance} />

      {isLoading ? (
        <div
          className="bg-surface border border-hairline rounded p-8 text-center motion-safe:animate-pulse"
          aria-busy="true"
        >
          <p className="text-sm text-ink-subtle">Loading models…</p>
        </div>
      ) : error ? (
        <div className="bg-surface border border-hairline rounded p-5">
          <p role="alert" className="text-sm text-negative">
            {extractMessage(error)}
          </p>
        </div>
      ) : (
        <section aria-labelledby="models-heading">
          <SectionHeader
            id="models-heading"
            title="Registered Models"
            subtitle="Newest first by training-window end. Click Detail to see full config, provenance, and validation metrics."
          />
          <ModelsTable models={models} />
        </section>
      )}

      <WalkForwardLauncher />
    </div>
  )
}
