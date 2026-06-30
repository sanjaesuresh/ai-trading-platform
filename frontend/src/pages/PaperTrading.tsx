import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  createDeployment,
  getKillSwitch,
  listDeployments,
  setKillSwitch,
} from '../api/paperTrading'
import { getStrategies } from '../api/strategies'
import {
  StrategyParamFields,
  defaultsFromSchema,
} from '../components/StrategyParamFields'
import { PaperDisclaimer } from '../components/PaperDisclaimer'
import { RunStatusBadge } from '../components/RunStatusBadge'
import type { StrategyInfo } from '../types/strategy'
import type {
  DeploymentRiskConfig,
  DeploymentSummary,
  KillSwitchStatus,
} from '../types/paperTrading'
import { formatCurrency, formatDate } from '../utils/format'
import { extractMessage } from '../utils/errors'

const DEFAULT_CONFIG: DeploymentRiskConfig = {
  fee_bps: 5,
  slippage_bps: 5,
  target_vol: null,
  vol_lookback: 20,
  max_position_pct: 0.95,
  gross_exposure_cap: 1.0,
  max_open_positions: 5,
  per_order_notional_cap: null,
  stop_loss_pct: null,
  take_profit_pct: null,
  max_drawdown_cutoff_pct: 0.2,
}

interface RiskField {
  key: keyof DeploymentRiskConfig
  label: string
  note?: string
  nullable?: boolean
}

const RISK_FIELDS: RiskField[] = [
  { key: 'gross_exposure_cap', label: 'Gross exposure cap', note: '1.0 = no leverage' },
  { key: 'max_open_positions', label: 'Max open positions' },
  { key: 'max_position_pct', label: 'Max position fraction', note: 'per symbol' },
  { key: 'max_drawdown_cutoff_pct', label: 'Drawdown kill', note: 'flatten + halt past this', nullable: true },
  { key: 'target_vol', label: 'Target volatility', note: 'blank = flat sizing', nullable: true },
  { key: 'vol_lookback', label: 'Vol lookback (bars)' },
  { key: 'fee_bps', label: 'Fee (bps)' },
  { key: 'slippage_bps', label: 'Slippage (bps)' },
  { key: 'per_order_notional_cap', label: 'Per-order notional cap', note: 'blank = none', nullable: true },
  { key: 'stop_loss_pct', label: 'Stop loss', note: 'blank = none', nullable: true },
  { key: 'take_profit_pct', label: 'Take profit', note: 'blank = none', nullable: true },
]

export default function PaperTrading() {
  const [deployments, setDeployments] = useState<DeploymentSummary[]>([])
  const [strategies, setStrategies] = useState<StrategyInfo[]>([])
  const [kill, setKill] = useState<KillSwitchStatus | null>(null)
  const [loadErr, setLoadErr] = useState<string | null>(null)

  // Create-form state.
  const [name, setName] = useState('')
  const [strategyName, setStrategyName] = useState('')
  const [params, setParams] = useState<Record<string, number>>({})
  const [symbolsText, setSymbolsText] = useState('SPY, AAPL, MSFT')
  const [capital, setCapital] = useState('100000')
  const [config, setConfig] = useState<DeploymentRiskConfig>(DEFAULT_CONFIG)
  const [submitting, setSubmitting] = useState(false)
  const [formErr, setFormErr] = useState<string | null>(null)
  const [formMsg, setFormMsg] = useState<string | null>(null)
  const [killBusy, setKillBusy] = useState(false)

  const refresh = async () => {
    try {
      const [deps, k] = await Promise.all([listDeployments(), getKillSwitch()])
      setDeployments(deps)
      setKill(k)
      setLoadErr(null)
    } catch (err) {
      setLoadErr(extractMessage(err))
    }
  }

  useEffect(() => {
    void refresh()
    void getStrategies()
      .then((s) => {
        setStrategies(s)
        if (s.length > 0) {
          setStrategyName(s[0].name)
          setParams(defaultsFromSchema(s[0].params_schema))
        }
      })
      .catch((err) => setLoadErr(extractMessage(err)))
  }, [])

  const selected = strategies.find((s) => s.name === strategyName)

  const onSelectStrategy = (next: string) => {
    setStrategyName(next)
    const s = strategies.find((x) => x.name === next)
    setParams(s ? defaultsFromSchema(s.params_schema) : {})
  }

  const setConfigField = (key: keyof DeploymentRiskConfig, raw: string, nullable?: boolean) => {
    const value = raw === '' ? (nullable ? null : Number.NaN) : Number(raw)
    setConfig((c) => ({ ...c, [key]: value }))
  }

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    setFormErr(null)
    setFormMsg(null)
    const symbols = symbolsText
      .split(',')
      .map((s) => s.trim().toUpperCase())
      .filter((s) => s.length > 0)
    setSubmitting(true)
    try {
      const created = await createDeployment({
        name,
        strategy_name: strategyName,
        params,
        symbols,
        starting_capital: Number(capital),
        config,
        enabled: true,
      })
      setFormMsg(`Created deployment #${created.id} (${created.name}).`)
      setName('')
      void refresh()
    } catch (err) {
      setFormErr(extractMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  const toggleKill = async () => {
    if (!kill) return
    setKillBusy(true)
    try {
      const next = await setKillSwitch(!kill.active, kill.active ? '' : 'Manually tripped from UI')
      setKill(next)
    } catch (err) {
      setLoadErr(extractMessage(err))
    } finally {
      setKillBusy(false)
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-xl font-semibold text-zinc-50">Paper Trading</h1>
        <p className="text-sm text-zinc-500 mt-1">
          Run a strategy forward across a basket against Alpaca paper, on the same
          portfolio core you can backtest.
        </p>
      </div>

      <PaperDisclaimer />

      {loadErr && (
        <p role="alert" className="text-sm text-rose-400">
          {loadErr}
        </p>
      )}

      <section aria-labelledby="kill-heading">
        <h2 id="kill-heading" className="text-xs font-medium text-zinc-500 uppercase tracking-wider mb-3">
          Global Kill Switch
        </h2>
        <div className="bg-zinc-900 border border-zinc-800 rounded p-4 flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-zinc-400">
            {kill === null ? (
              <span className="text-zinc-500">Loading kill-switch state…</span>
            ) : kill.active ? (
              <span className="text-rose-400 font-medium">
                ACTIVE — all new orders are halted.
              </span>
            ) : (
              'Inactive. Tripping it halts all new orders across every deployment.'
            )}
          </p>
          <button
            type="button"
            onClick={() => void toggleKill()}
            disabled={kill === null || killBusy}
            aria-busy={killBusy}
            aria-pressed={kill?.active ?? false}
            className={`px-3 py-1.5 text-sm font-semibold rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
              kill?.active
                ? 'bg-emerald-500 text-zinc-950 hover:bg-emerald-400'
                : 'bg-rose-500 text-zinc-50 hover:bg-rose-400'
            }`}
          >
            {kill === null
              ? 'Loading…'
              : kill.active
                ? 'Clear kill switch'
                : 'Trip kill switch'}
          </button>
        </div>
      </section>

      <section aria-labelledby="create-heading">
        <h2 id="create-heading" className="text-xs font-medium text-zinc-500 uppercase tracking-wider mb-3">
          Create a Deployment
        </h2>
        <form
          onSubmit={(e) => void handleCreate(e)}
          className="bg-zinc-900 border border-zinc-800 rounded p-5 space-y-4"
        >
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label htmlFor="dep-name" className="block text-xs text-zinc-400 font-medium mb-1">
                Name
              </label>
              <input
                id="dep-name"
                type="text"
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Large-cap trend basket"
                className="w-full bg-zinc-950 border border-zinc-700 rounded px-2 py-1.5 text-sm font-mono text-zinc-50 focus:border-amber-400 focus:outline-none"
              />
            </div>
            <div>
              <label htmlFor="dep-strategy" className="block text-xs text-zinc-400 font-medium mb-1">
                Strategy
              </label>
              <select
                id="dep-strategy"
                value={strategyName}
                onChange={(e) => onSelectStrategy(e.target.value)}
                className="w-full bg-zinc-950 border border-zinc-700 rounded px-2 py-1.5 text-sm font-mono text-zinc-50 focus:border-amber-400 focus:outline-none"
              >
                {strategies.map((s) => (
                  <option key={s.name} value={s.name}>
                    {s.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="dep-symbols" className="block text-xs text-zinc-400 font-medium mb-1">
                Symbols
              </label>
              <input
                id="dep-symbols"
                type="text"
                value={symbolsText}
                onChange={(e) => setSymbolsText(e.target.value)}
                placeholder="comma-separated, e.g. SPY, AAPL, MSFT"
                className="w-full bg-zinc-950 border border-zinc-700 rounded px-2 py-1.5 text-sm font-mono text-zinc-50 focus:border-amber-400 focus:outline-none"
              />
            </div>
            <div>
              <label htmlFor="dep-capital" className="block text-xs text-zinc-400 font-medium mb-1">
                Starting capital (USD)
              </label>
              <input
                id="dep-capital"
                type="number"
                step="any"
                min="1"
                value={capital}
                onChange={(e) => setCapital(e.target.value)}
                className="w-full bg-zinc-950 border border-zinc-700 rounded px-2 py-1.5 text-sm font-mono text-zinc-50 focus:border-amber-400 focus:outline-none"
              />
            </div>
          </div>

          {selected && (
            <fieldset className="border border-zinc-800 rounded p-4">
              <legend className="text-xs text-zinc-500 uppercase tracking-wider px-1">
                Strategy parameters
              </legend>
              <StrategyParamFields schema={selected.params_schema} values={params} onChange={setParams} />
            </fieldset>
          )}

          <fieldset className="border border-zinc-800 rounded p-4">
            <legend className="text-xs text-zinc-500 uppercase tracking-wider px-1">
              Risk limits
            </legend>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
              {RISK_FIELDS.map((f) => {
                const v = config[f.key]
                return (
                  <div key={f.key}>
                    <label htmlFor={`cfg-${f.key}`} className="block text-xs text-zinc-400 font-medium mb-1">
                      {f.label}
                    </label>
                    <input
                      id={`cfg-${f.key}`}
                      type="number"
                      step="any"
                      value={v === null || v === undefined || Number.isNaN(v) ? '' : v}
                      onChange={(e) => setConfigField(f.key, e.target.value, f.nullable)}
                      className="w-full bg-zinc-950 border border-zinc-700 rounded px-2 py-1.5 text-sm font-mono text-zinc-50 focus:border-amber-400 focus:outline-none"
                    />
                    {f.note && <p className="text-xs text-zinc-500 mt-1">{f.note}</p>}
                  </div>
                )
              })}
            </div>
          </fieldset>

          <div className="flex flex-wrap items-center gap-3">
            <button
              type="submit"
              disabled={submitting}
              aria-busy={submitting}
              className="inline-flex items-center gap-2 px-4 py-2 bg-amber-400 text-zinc-950 text-sm font-semibold rounded transition-colors hover:bg-amber-300 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {submitting ? 'Creating…' : 'Create Deployment'}
            </button>
            <span className="text-xs text-zinc-500">
              Enabling this disables any other deployment (one shared paper account).
            </span>
            {formMsg && (
              <p role="status" className="text-sm text-emerald-400">
                {formMsg}
              </p>
            )}
          </div>
          {formErr !== null && (
            <p role="alert" className="text-sm text-rose-400">
              {formErr}
            </p>
          )}
        </form>
      </section>

      <section aria-labelledby="list-heading">
        <h2 id="list-heading" className="text-xs font-medium text-zinc-500 uppercase tracking-wider mb-3">
          Deployments
        </h2>
        {deployments.length === 0 ? (
          <div className="bg-zinc-900 border border-zinc-800 rounded p-8 text-center">
            <p className="text-sm text-zinc-500">No deployments yet. Create one above.</p>
          </div>
        ) : (
          <div className="bg-zinc-900 border border-zinc-800 rounded overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-zinc-500 uppercase tracking-wider border-b border-zinc-800">
                  <th className="px-3 py-2 font-medium">ID</th>
                  <th className="px-3 py-2 font-medium">Name</th>
                  <th className="px-3 py-2 font-medium">Strategy</th>
                  <th className="px-3 py-2 font-medium">Symbols</th>
                  <th className="px-3 py-2 font-medium">Capital</th>
                  <th className="px-3 py-2 font-medium">Enabled</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium">Created</th>
                </tr>
              </thead>
              <tbody>
                {deployments.map((d) => (
                  <tr key={d.id} className="border-b border-zinc-800/60 last:border-0">
                    <td className="px-3 py-2 font-mono text-zinc-400">#{d.id}</td>
                    <td className="px-3 py-2">
                      <Link to={`/paper/${d.id}`} className="text-amber-400 hover:text-amber-300">
                        {d.name}
                      </Link>
                    </td>
                    <td className="px-3 py-2 text-zinc-400">{d.strategy_name}</td>
                    <td className="px-3 py-2 font-mono text-xs text-zinc-500">
                      {d.symbols.join(', ')}
                    </td>
                    <td className="px-3 py-2 font-mono text-zinc-400">
                      {formatCurrency(d.starting_capital)}
                    </td>
                    <td className="px-3 py-2">
                      {d.enabled ? (
                        <span className="text-emerald-400">on</span>
                      ) : (
                        <span className="text-zinc-500">off</span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <RunStatusBadge status={d.status} />
                    </td>
                    <td className="px-3 py-2 font-mono text-xs text-zinc-500">
                      {formatDate(d.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
