/**
 * Disclaimer for news / LLM surfaces. News-driven signals are the noisiest,
 * most overfit-prone input the platform touches, and LLM-derived sentiment is
 * easily misread as an oracle — so every news surface says plainly that it is a
 * research signal, not advice, and that a null result is the expected outcome.
 */
export function NewsDisclaimer() {
  return (
    <div
      role="note"
      aria-label="News research disclaimer"
      className="bg-caution/10 border border-caution/25 rounded-lg p-4"
    >
      <p className="text-sm text-caution font-semibold">
        <span aria-hidden className="mr-1.5">📰</span>
        Simulated news research — LLM sentiment is a research signal, not advice.
      </p>
      <p className="text-xs text-caution/80 mt-1.5 leading-relaxed">
        News is the noisiest, most overfit-prone input here. The ablation charges
        the real LLM cost against the news result and tests the increment on its
        own, so{' '}
        <strong className="text-caution">
          "news does not add value" is the expected, valid outcome
        </strong>{' '}
        — not a failure. LLM-labelled sentiment can be wrong or stale; it never
        implies a trade. No real money. Not financial advice. Past performance
        does not guarantee future results.
      </p>
    </div>
  )
}
