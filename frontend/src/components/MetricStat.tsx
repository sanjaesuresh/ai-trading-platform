import type { Metrics } from '../types/backtest'
import { METRIC_DEFS } from '../lib/metricDefinitions'
import { Stat } from './ui'

interface MetricStatProps {
  metricKey: keyof Metrics
  value: number
  /** Override the canonical definition caption with extra context. */
  hint?: string
}

/** A Stat block driven entirely by the canonical metric definition. */
export function MetricStat({ metricKey, value, hint }: MetricStatProps) {
  const def = METRIC_DEFS[metricKey]
  return (
    <Stat
      label={def.label}
      value={def.format(value)}
      unit={def.unit}
      tone={def.tone?.(value)}
      hint={hint ?? def.definition}
    />
  )
}
