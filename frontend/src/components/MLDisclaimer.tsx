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
      className="bg-amber-950/40 border border-amber-900/50 rounded p-4"
    >
      <p className="text-sm text-amber-200/90 font-medium">
        Simulated ML research — not a signal, not financial advice.
      </p>
      <p className="text-xs text-amber-300/70 mt-1 leading-relaxed">
        Results are out-of-sample and net of transaction costs, but ML on daily
        bars is one of the easiest places to fool yourself: a model can appear to
        beat a baseline while actually capturing overfitting, survivorship, or a
        regime that will not persist.{' '}
        <strong className="text-amber-300/90">
          Inconclusive is the expected outcome
        </strong>{' '}
        on thin daily data — it is not a near-miss or a soft pass. A verdict of
        "pass" is <strong className="text-amber-300/90">not</strong> a signal to
        trade real money; it means the strategy survived this significance
        battery, nothing more. No real money. Not financial advice. Past
        performance does not guarantee future results.
      </p>
    </div>
  )
}
