import { RunForm } from '../components/RunForm'

export default function NewRun() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-zinc-50">New Backtest</h1>
        <p className="text-sm text-zinc-500 mt-1">
          Pick a symbol and strategy, tune its parameters, and run a simulated
          backtest. Historical data only — not financial advice.
        </p>
      </div>
      <div className="bg-zinc-900 border border-zinc-800 rounded p-5 max-w-4xl">
        <RunForm />
      </div>
    </div>
  )
}
