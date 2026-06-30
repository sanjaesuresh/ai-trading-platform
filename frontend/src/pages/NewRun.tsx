import { RunForm } from '../components/RunForm'
import { PageIntro } from '../components/ui'

export default function NewRun() {
  return (
    <div className="space-y-6 max-w-4xl">
      <PageIntro title="Start a new backtest" icon="🧪" eyebrow="New Run">
        Pick a symbol and a strategy, adjust its settings, and run it over
        historical prices. You&apos;ll get back a full performance report — returns,
        risk, and every simulated trade — with realistic fees and slippage already
        subtracted. It&apos;s a what-if on past data, not a prediction.
      </PageIntro>
      <div className="bg-surface border border-hairline rounded-lg p-5 shadow-card">
        <RunForm />
      </div>
    </div>
  )
}
