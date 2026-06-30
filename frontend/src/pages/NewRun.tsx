import { RunForm } from '../components/RunForm'
import { PageHeader } from '../components/ui'

export default function NewRun() {
  return (
    <div className="space-y-6 max-w-4xl">
      <PageHeader
        title="New Backtest"
        subtitle="Pick a symbol and strategy, tune its parameters, and run a simulated backtest net of fees and slippage. Historical data only — not financial advice."
      />
      <div className="bg-zinc-900 border border-zinc-800 rounded p-5">
        <RunForm />
      </div>
    </div>
  )
}
