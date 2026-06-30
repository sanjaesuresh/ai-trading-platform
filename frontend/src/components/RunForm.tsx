import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getStrategies } from '../api/strategies'
import { runBacktest } from '../api/backtests'
import type { RunRequest } from '../types/backtest'
import type { StrategyInfo } from '../types/strategy'
import { StrategyParamFields, defaultsFromSchema } from './StrategyParamFields'
import { SectionHeader, Field, inputClass, Term } from './ui'
import { extractMessage } from '../utils/errors'

interface TextFieldProps {
  id: string
  label: string
  value: string
  onChange: (v: string) => void
  type?: string
  placeholder?: string
  hint?: string
  unit?: string
  step?: string
}

function TextField({ id, label, value, onChange, type = 'text', placeholder, hint, unit, step }: TextFieldProps) {
  return (
    <Field label={label} htmlFor={id} unit={unit} hint={hint}>
      <input
        id={id}
        type={type}
        step={step}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className={inputClass}
      />
    </Field>
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

  return (
    <form onSubmit={(e) => void handleSubmit(e)} className="space-y-8">
      <p className="text-xs text-caution/80">
        Simulated only — results are backtests on historical data, not financial advice.
      </p>

      {/* Data source */}
      <section>
        <SectionHeader title="Data Source" subtitle="Where the price bars come from." />
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <TextField
            id="symbol"
            label="Symbol"
            value={symbol}
            onChange={setSymbol}
            placeholder="e.g. SPY"
            hint="Run label (CSV mode) or the stored-bar lookup key (DB mode)."
          />
          <TextField
            id="csv_path"
            label="CSV Path"
            unit="optional"
            value={csvPath}
            onChange={setCsvPath}
            placeholder="leave empty for DB mode"
            hint="A path under the allowed data directory. Empty = read stored bars for the symbol."
          />
        </div>
      </section>

      {/* Strategy */}
      <section>
        <SectionHeader title="Strategy" subtitle="The rule set and its parameters." />
        {stratError !== null ? (
          <div className="bg-surface border border-hairline rounded-lg p-4">
            <p role="alert" className="text-sm text-negative">{stratError}</p>
            <button
              type="button"
              onClick={loadStrategies}
              className="mt-2 text-sm text-accent hover:text-accent-bright"
            >
              Retry
            </button>
          </div>
        ) : strategies === null ? (
          <p className="text-sm text-ink-subtle" aria-busy="true">Loading strategies…</p>
        ) : (
          <div className="space-y-4">
            <Field label="Strategy" htmlFor="strategy">
              <select
                id="strategy"
                value={strategyName}
                onChange={(e) => onStrategyChange(e.target.value)}
                className={`${inputClass} sm:w-64`}
              >
                {strategies.map((s) => (
                  <option key={s.name} value={s.name}>{s.name}</option>
                ))}
              </select>
            </Field>
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
        <SectionHeader
          title="Execution"
          subtitle={
            <>
              Starting capital and the trading frictions —{' '}
              <Term id="fees">fees</Term> and <Term id="slippage">slippage</Term> —
              applied to every fill.
            </>
          }
        />
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <TextField id="capital" label="Initial Capital" unit="USD" type="number" step="any" value={initialCapital} onChange={setInitialCapital} />
          <TextField id="fee" label="Fee" unit="bps" type="number" step="any" value={feeBps} onChange={setFeeBps} hint="Commission per fill, basis points." />
          <TextField id="slippage" label="Slippage" unit="bps" type="number" step="any" value={slippageBps} onChange={setSlippageBps} hint="Modeled price impact per fill." />
          <TextField id="maxpos" label="Max Position" unit="fraction" type="number" step="any" value={maxPositionPct} onChange={setMaxPositionPct} hint="Share of cash per position. 0.95 = 95%." />
        </div>
      </section>

      {/* Sizing & risk (optional) */}
      <section>
        <SectionHeader
          title="Sizing & Risk"
          subtitle={
            <>
              Optional safety controls —{' '}
              <Term id="vol_targeting">volatility targeting</Term>,{' '}
              <Term id="stop_loss">stop loss</Term>,{' '}
              <Term id="take_profit">take profit</Term>, and a{' '}
              <Term id="drawdown_kill">drawdown kill-switch</Term>. Leave a field
              empty to turn it off.
            </>
          }
        />
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          <TextField id="targetvol" label="Target Volatility" unit="annual" type="number" step="any" value={targetVol} onChange={setTargetVol} hint="e.g. 0.15 = 15%. Empty = fixed sizing." />
          <TextField id="vollookback" label="Vol Lookback" unit="bars" type="number" step="any" value={volLookback} onChange={setVolLookback} hint="Used only when target volatility is set." />
          <TextField id="stoploss" label="Stop Loss" unit="fraction" type="number" step="any" value={stopLossPct} onChange={setStopLossPct} hint="Exit if a position falls this far." />
          <TextField id="takeprofit" label="Take Profit" unit="fraction" type="number" step="any" value={takeProfitPct} onChange={setTakeProfitPct} hint="Exit if a position gains this far." />
          <TextField id="maxdd" label="Max Drawdown Cutoff" unit="fraction" type="number" step="any" value={maxDrawdownCutoffPct} onChange={setMaxDrawdownCutoffPct} hint="Halt trading past this equity decline." />
        </div>
      </section>

      {error !== null && (
        <p role="alert" className="text-sm text-negative">{error}</p>
      )}

      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={submitting || strategies === null}
          aria-busy={submitting}
          className="inline-flex items-center gap-2 px-4 py-2 bg-accent text-canvas text-sm font-semibold rounded-lg transition-colors hover:bg-accent-bright disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {submitting ? 'Running…' : 'Run Backtest'}
        </button>
      </div>
    </form>
  )
}
