import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getStrategies } from '../api/strategies'
import { runBacktest } from '../api/backtests'
import type { RunRequest } from '../types/backtest'
import type { StrategyInfo } from '../types/strategy'
import { StrategyParamFields, defaultsFromSchema } from './StrategyParamFields'
import { extractMessage } from '../utils/errors'

interface FieldProps {
  id: string
  label: string
  value: string
  onChange: (v: string) => void
  type?: string
  placeholder?: string
  hint?: string
  step?: string
}

function Field({ id, label, value, onChange, type = 'text', placeholder, hint, step }: FieldProps) {
  return (
    <div>
      <label htmlFor={id} className="block text-xs text-zinc-400 font-medium mb-1">
        {label}
      </label>
      <input
        id={id}
        type={type}
        step={step}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="w-full bg-zinc-950 border border-zinc-700 rounded px-2 py-1.5 text-sm font-mono text-zinc-50 focus:border-amber-400 focus:outline-none"
      />
      {hint && <p className="text-xs text-zinc-600 mt-1">{hint}</p>}
    </div>
  )
}

// Empty string → omit (the engine treats the control as disabled); otherwise a number.
function optionalNumber(s: string): number | undefined {
  const t = s.trim()
  return t === '' ? undefined : Number(t)
}

export function RunForm() {
  const navigate = useNavigate()

  const [strategies, setStrategies] = useState<StrategyInfo[] | null>(null)
  const [stratError, setStratError] = useState<string | null>(null)

  const [symbol, setSymbol] = useState('SYNTH')
  const [csvPath, setCsvPath] = useState('data/sample/sample_ohlcv.csv')
  const [strategyName, setStrategyName] = useState('')
  const [params, setParams] = useState<Record<string, number>>({})

  const [initialCapital, setInitialCapital] = useState('100000')
  const [feeBps, setFeeBps] = useState('5')
  const [slippageBps, setSlippageBps] = useState('5')
  const [maxPositionPct, setMaxPositionPct] = useState('0.95')

  const [targetVol, setTargetVol] = useState('')
  const [volLookback, setVolLookback] = useState('20')
  const [stopLossPct, setStopLossPct] = useState('')
  const [takeProfitPct, setTakeProfitPct] = useState('')
  const [maxDrawdownCutoffPct, setMaxDrawdownCutoffPct] = useState('')

  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadStrategies = () => {
    setStratError(null)
    getStrategies()
      .then((list) => {
        setStrategies(list)
        if (list.length > 0) {
          setStrategyName(list[0].name)
          setParams(defaultsFromSchema(list[0].params_schema))
        }
      })
      .catch((err) => setStratError(extractMessage(err)))
  }

  useEffect(loadStrategies, [])

  const selected = strategies?.find((s) => s.name === strategyName)

  const onStrategyChange = (name: string) => {
    setStrategyName(name)
    const next = strategies?.find((s) => s.name === name)
    setParams(next ? defaultsFromSchema(next.params_schema) : {})
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)

    if (symbol.trim() === '') {
      setError('Symbol is required.')
      return
    }
    if (Object.values(params).some((v) => Number.isNaN(v))) {
      setError('Every strategy parameter needs a value.')
      return
    }

    const req: RunRequest = {
      symbol: symbol.trim(),
      csv_path: csvPath.trim() === '' ? undefined : csvPath.trim(),
      strategy_name: strategyName,
      strategy_params: params,
      initial_capital: Number(initialCapital),
      fee_bps: Number(feeBps),
      slippage_bps: Number(slippageBps),
      max_position_pct: Number(maxPositionPct),
    }
    const tv = optionalNumber(targetVol)
    if (tv !== undefined) {
      req.target_vol = tv
      req.vol_lookback = Number(volLookback)
    }
    req.stop_loss_pct = optionalNumber(stopLossPct)
    req.take_profit_pct = optionalNumber(takeProfitPct)
    req.max_drawdown_cutoff_pct = optionalNumber(maxDrawdownCutoffPct)

    setSubmitting(true)
    try {
      const summary = await runBacktest(req)
      navigate(`/backtests/${summary.id}`)
    } catch (err) {
      setError(extractMessage(err))
      setSubmitting(false)
    }
  }

  const sectionLabel = 'text-xs font-medium text-zinc-500 uppercase tracking-wider mb-3'

  return (
    <form onSubmit={(e) => void handleSubmit(e)} className="space-y-8">
      <p className="text-xs text-amber-300/70">
        Simulated only — results are backtests on historical data, not financial advice.
      </p>

      {/* Data source */}
      <section>
        <h2 className={sectionLabel}>Data Source</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Field
            id="symbol"
            label="Symbol"
            value={symbol}
            onChange={setSymbol}
            placeholder="e.g. SPY"
            hint="Run label (CSV mode) or the stored-bar lookup key (DB mode)."
          />
          <Field
            id="csv_path"
            label="CSV path (optional)"
            value={csvPath}
            onChange={setCsvPath}
            placeholder="leave empty for DB mode"
            hint="A path under the allowed data directory. Empty = read stored bars for the symbol."
          />
        </div>
      </section>

      {/* Strategy */}
      <section>
        <h2 className={sectionLabel}>Strategy</h2>
        {stratError !== null ? (
          <div className="bg-zinc-900 border border-zinc-800 rounded p-4">
            <p role="alert" className="text-sm text-rose-400">
              {stratError}
            </p>
            <button
              type="button"
              onClick={loadStrategies}
              className="mt-2 text-sm text-amber-400 hover:text-amber-300"
            >
              Retry
            </button>
          </div>
        ) : strategies === null ? (
          <p className="text-sm text-zinc-500" aria-busy="true">
            Loading strategies…
          </p>
        ) : (
          <div className="space-y-4">
            <div>
              <label
                htmlFor="strategy"
                className="block text-xs text-zinc-400 font-medium mb-1"
              >
                Strategy
              </label>
              <select
                id="strategy"
                value={strategyName}
                onChange={(e) => onStrategyChange(e.target.value)}
                className="w-full sm:w-64 bg-zinc-950 border border-zinc-700 rounded px-2 py-1.5 text-sm font-mono text-zinc-50 focus:border-amber-400 focus:outline-none"
              >
                {strategies.map((s) => (
                  <option key={s.name} value={s.name}>
                    {s.name}
                  </option>
                ))}
              </select>
            </div>
            {selected && (
              <StrategyParamFields
                schema={selected.params_schema}
                values={params}
                onChange={setParams}
              />
            )}
          </div>
        )}
      </section>

      {/* Execution */}
      <section>
        <h2 className={sectionLabel}>Execution</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <Field id="capital" label="Initial capital ($)" type="number" step="any" value={initialCapital} onChange={setInitialCapital} />
          <Field id="fee" label="Fee (bps)" type="number" step="any" value={feeBps} onChange={setFeeBps} />
          <Field id="slippage" label="Slippage (bps)" type="number" step="any" value={slippageBps} onChange={setSlippageBps} />
          <Field id="maxpos" label="Max position (fraction)" type="number" step="any" value={maxPositionPct} onChange={setMaxPositionPct} />
        </div>
      </section>

      {/* Sizing & risk (optional) */}
      <section>
        <h2 className={sectionLabel}>Sizing & Risk (optional)</h2>
        <p className="text-xs text-zinc-600 mb-3">Leave a field empty to disable that control.</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          <Field id="targetvol" label="Target volatility (e.g. 0.15)" type="number" step="any" value={targetVol} onChange={setTargetVol} />
          <Field id="vollookback" label="Vol lookback (bars)" type="number" step="any" value={volLookback} onChange={setVolLookback} hint="Used only when target volatility is set." />
          <Field id="stoploss" label="Stop loss (fraction)" type="number" step="any" value={stopLossPct} onChange={setStopLossPct} />
          <Field id="takeprofit" label="Take profit (fraction)" type="number" step="any" value={takeProfitPct} onChange={setTakeProfitPct} />
          <Field id="maxdd" label="Max drawdown cutoff (fraction)" type="number" step="any" value={maxDrawdownCutoffPct} onChange={setMaxDrawdownCutoffPct} />
        </div>
      </section>

      {error !== null && (
        <p role="alert" className="text-sm text-rose-400">
          {error}
        </p>
      )}

      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={submitting || strategies === null}
          aria-busy={submitting}
          className="inline-flex items-center gap-2 px-4 py-2 bg-amber-400 text-zinc-950 text-sm font-semibold rounded transition-colors hover:bg-amber-300 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {submitting ? 'Running…' : 'Run Backtest'}
        </button>
      </div>
    </form>
  )
}
