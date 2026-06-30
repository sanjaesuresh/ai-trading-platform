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
import { PageHeader, SectionHeader, Field, inputClass, Table, Th, Td } from '../components/ui'
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
  unit?: string
  note?: string
  nullable?: boolean
}

const RISK_FIELDS: RiskField[] = [
  { key: 'gross_exposure_cap', label: 'Gross Exposure Cap', unit: '×', note: '1.0 = no leverage' },
  { key: 'max_open_positions', label: 'Max Open Positions', unit: 'count' },
  { key: 'max_position_pct', label: 'Max Position', unit: 'fraction', note: 'Per symbol' },
  { key: 'max_drawdown_cutoff_pct', label: 'Drawdown Kill', unit: 'fraction', note: 'Flatten + halt past this', nullable: true },
  { key: 'target_vol', label: 'Target Volatility', unit: 'annual', note: 'Blank = flat sizing', nullable: true },
  { key: 'vol_lookback', label: 'Vol Lookback', unit: 'bars' },
  { key: 'fee_bps', label: 'Fee', unit: 'bps' },
  { key: 'slippage_bps', label: 'Slippage', unit: 'bps' },
  { key: 'per_order_notional_cap', label: 'Per-Order Notional Cap', unit: 'USD', note: 'Blank = none', nullable: true },
  { key: 'stop_loss_pct', label: 'Stop Loss', unit: 'fraction', note: 'Blank = none', nullable: true },
  { key: 'take_profit_pct', label: 'Take Profit', unit: 'fraction', note: 'Blank = none', nullable: true },
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
      <PageHeader
        title="Paper Trading"
        subtitle="Run a strategy forward across a basket against Alpaca's paper endpoint, on the same portfolio core you backtest with. Simulated only — no real money."
      />

      <PaperDisclaimer />

      {loadErr && (
        <p role="alert" className="text-sm text-rose-400">{loadErr}</p>
      )}

      <section aria-labelledby="kill-heading">
        <SectionHeader
          id="kill-heading"
          title="Global Kill Switch"
          subtitle="A single master stop. While active, no deployment can submit a new order."
        />
        <div className="bg-zinc-900 border border-zinc-800 rounded p-4 flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-zinc-400">
            {kill === null ? (
              <span className="text-zinc-500">Loading kill-switch state…</span>
            ) : kill.active ? (
              <span className="text-rose-400 font-medium">ACTIVE — all new orders are halted.</span>
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
            {kill === null ? 'Loading…' : kill.active ? 'Clear kill switch' : 'Trip kill switch'}
          </button>
        </div>
      </section>

      <section aria-labelledby="create-heading">
        <SectionHeader
          id="create-heading"
          title="Create a Deployment"
          subtitle="Define the basket, the strategy, and the risk limits the portfolio core enforces on every order."
        />
        <form
          onSubmit={(e) => void handleCreate(e)}
          className="bg-zinc-900 border border-zinc-800 rounded p-5 space-y-4"
        >
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Field label="Name" htmlFor="dep-name">
              <input
                id="dep-name"
                type="text"
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Large-cap trend basket"
                className={inputClass}
              />
            </Field>
            <Field label="Strategy" htmlFor="dep-strategy">
              <select
                id="dep-strategy"
                value={strategyName}
                onChange={(e) => onSelectStrategy(e.target.value)}
                className={inputClass}
              >
                {strategies.map((s) => (
                  <option key={s.name} value={s.name}>{s.name}</option>
                ))}
              </select>
            </Field>
            <Field label="Symbols" htmlFor="dep-symbols" hint="Comma-separated basket of tickers.">
              <input
                id="dep-symbols"
                type="text"
                value={symbolsText}
                onChange={(e) => setSymbolsText(e.target.value)}
                placeholder="e.g. SPY, AAPL, MSFT"
                className={inputClass}
              />
            </Field>
            <Field label="Starting Capital" htmlFor="dep-capital" unit="USD">
              <input
                id="dep-capital"
                type="number"
                step="any"
                min="1"
                value={capital}
                onChange={(e) => setCapital(e.target.value)}
                className={inputClass}
              />
            </Field>
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
                  <Field key={f.key} label={f.label} htmlFor={`cfg-${f.key}`} unit={f.unit} hint={f.note}>
                    <input
                      id={`cfg-${f.key}`}
                      type="number"
                      step="any"
                      value={v === null || v === undefined || Number.isNaN(v) ? '' : v}
                      onChange={(e) => setConfigField(f.key, e.target.value, f.nullable)}
                      className={inputClass}
                    />
                  </Field>
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
              <p role="status" className="text-sm text-emerald-400">{formMsg}</p>
            )}
          </div>
          {formErr !== null && (
            <p role="alert" className="text-sm text-rose-400">{formErr}</p>
          )}
        </form>
      </section>

      <section aria-labelledby="list-heading">
        <SectionHeader
          id="list-heading"
          title="Deployments"
          subtitle="Every paper deployment and whether it is currently allowed to trade."
          right={
            deployments.length > 0 ? (
              <span className="font-mono text-xs text-zinc-500">{deployments.length} total</span>
            ) : undefined
          }
        />
        {deployments.length === 0 ? (
          <div className="bg-zinc-900 border border-zinc-800 rounded p-8 text-center">
            <p className="text-sm text-zinc-500">No deployments yet. Create one above.</p>
          </div>
        ) : (
          <div className="bg-zinc-900 border border-zinc-800 rounded px-4 py-3">
            <Table>
              <thead>
                <tr className="border-b border-zinc-800">
                  <Th>ID</Th>
                  <Th>Name</Th>
                  <Th>Strategy</Th>
                  <Th>Symbols</Th>
                  <Th align="right" sub="USD">Capital</Th>
                  <Th>Enabled</Th>
                  <Th>Status</Th>
                  <Th align="right">Created</Th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800/60">
                {deployments.map((d) => (
                  <tr key={d.id} className="hover:bg-zinc-800/30 transition-colors">
                    <Td mono className="text-zinc-400">#{d.id}</Td>
                    <Td>
                      <Link to={`/paper/${d.id}`} className="text-amber-400 hover:text-amber-300 transition-colors">
                        {d.name}
                      </Link>
                    </Td>
                    <Td className="text-zinc-400 text-xs">{d.strategy_name}</Td>
                    <Td mono className="text-zinc-500 text-xs">{d.symbols.join(', ')}</Td>
                    <Td mono align="right" className="text-zinc-300">{formatCurrency(d.starting_capital)}</Td>
                    <Td>
                      {d.enabled ? (
                        <span className="text-emerald-400 font-mono text-xs">on</span>
                      ) : (
                        <span className="text-zinc-500 font-mono text-xs">off</span>
                      )}
                    </Td>
                    <Td><RunStatusBadge status={d.status} /></Td>
                    <Td mono align="right" className="text-zinc-500">{formatDate(d.created_at)}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>
        )}
      </section>
    </div>
  )
}
