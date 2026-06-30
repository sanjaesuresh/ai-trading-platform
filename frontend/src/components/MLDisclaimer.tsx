/**
 * Strongest disclaimer treatment for ML surfaces. An "AI prediction" is the
 * most misreadable surface in the app — every ML page must carry both the
 * simulated-only caveat and the overfitting/leakage warning.
 */
export function MLDisclaimer() {
  return (
    <div
      role="note"
      aria-label="ML research disclaimer"
      className="bg-caution/10 border border-caution/25 rounded-lg p-4"
    >
      <p className="text-sm text-caution font-semibold">
        <span aria-hidden className="mr-1.5">⚠️</span>
        Simulated ML research — not a signal, not financial advice.
      </p>
      <p className="text-xs text-caution/80 mt-1.5 leading-relaxed">
        Results are out-of-sample and net of transaction costs, but ML on daily
        bars is one of the easiest places to fool yourself: a model can appear to
        beat a baseline while actually capturing overfitting, survivorship, or a
        regime that will not persist.{' '}
        <strong className="text-caution">
          Inconclusive is the expected outcome
        </strong>{' '}
        on thin daily data — it is not a near-miss or a soft pass. A verdict of
        "pass" is <strong className="text-caution">not</strong> a signal to
        trade real money; it means the strategy survived this significance
        battery, nothing more. No real money. Not financial advice. Past
        performance does not guarantee future results.
      </p>
    </div>
  )
}
