import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'
import type { EquityPoint } from '../types/backtest'
import { formatCurrency } from '../utils/format'

interface EquityCurveProps {
  data: EquityPoint[]
}

function xTick(value: string | number): string {
  const d = new Date(String(value))
  const m = (d.getMonth() + 1).toString().padStart(2, '0')
  const y = d.getFullYear().toString().slice(2)
  return `${m}/'${y}`
}

function yTick(value: string | number): string {
  const n = Number(value)
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}k`
  return `$${n.toFixed(0)}`
}

function labelFmt(label: string | number): string {
  return new Date(String(label)).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

export function EquityCurve({ data }: EquityCurveProps) {
  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 text-zinc-500 text-sm">
        No equity curve data available.
      </div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={300}>
      <LineChart data={data} margin={{ top: 8, right: 16, left: 8, bottom: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#27272a" vertical={false} />
        <XAxis
          dataKey="timestamp"
          tickFormatter={xTick}
          tick={{ fill: '#71717a', fontSize: 11, fontFamily: 'monospace' }}
          stroke="#3f3f46"
          tickLine={false}
          axisLine={{ stroke: '#3f3f46' }}
          minTickGap={50}
        />
        <YAxis
          tickFormatter={yTick}
          tick={{ fill: '#71717a', fontSize: 11, fontFamily: 'monospace' }}
          tickLine={false}
          axisLine={false}
          width={64}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: '#18181b',
            border: '1px solid #3f3f46',
            borderRadius: '4px',
            padding: '8px 12px',
          }}
          labelStyle={{ color: '#71717a', fontSize: '11px', marginBottom: '4px' }}
          itemStyle={{ color: '#fbbf24', fontSize: '12px', fontFamily: 'monospace' }}
          labelFormatter={labelFmt}
          formatter={(value) => [formatCurrency(value as number), 'Equity']}
        />
        <Line
          type="monotone"
          dataKey="equity"
          stroke="#fbbf24"
          strokeWidth={1.5}
          dot={false}
          activeDot={{ r: 3, fill: '#fbbf24', stroke: '#09090b', strokeWidth: 2 }}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}
