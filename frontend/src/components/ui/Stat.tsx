import type { ReactNode } from 'react'
import type { Tone } from '../../lib/metricDefinitions'

export function toneClass(tone: Tone | undefined): string {
  if (tone === 'pos') return 'text-positive'
  if (tone === 'neg') return 'text-negative'
  return 'text-ink'
}

interface StatProps {
  label: string
  value: ReactNode
  /** Unit suffix shown small and muted after the value (e.g. "days", "%"). */
  unit?: string
  /** One-line caption under the value: a definition or extra context. */
  hint?: ReactNode
  tone?: Tone
  /** Render the value in monospace tabular figures. Default true. */
  mono?: boolean
}

/**
 * The signature labeled stat block: uppercase micro LABEL, a tabular value with
 * its unit, and a one-line caption that defines the metric or gives context.
 * Every standalone number on the platform is rendered through this.
 */
export function Stat({ label, value, unit, hint, tone, mono = true }: StatProps) {
  return (
    <div className="bg-surface border border-hairline rounded-lg p-4 shadow-card">
      <dt className="text-[11px] font-medium text-ink-subtle uppercase tracking-wider">
        {label}
      </dt>
      <dd className="mt-1.5 flex items-baseline gap-1">
        <span
          className={`text-xl font-semibold ${mono ? 'font-mono' : ''} ${toneClass(tone)}`}
        >
          {value}
        </span>
        {unit !== undefined && (
          <span className="text-xs text-ink-subtle font-medium">{unit}</span>
        )}
      </dd>
      {hint !== undefined && (
        <p className="mt-1.5 text-[11px] leading-snug text-ink-subtle">{hint}</p>
      )}
    </div>
  )
}

interface StatGridProps {
  children: ReactNode
  /** Tailwind column classes. Default: 2 on mobile, 4 on md+. */
  cols?: string
}

export function StatGrid({
  children,
  cols = 'grid-cols-2 md:grid-cols-4',
}: StatGridProps) {
  return <dl className={`grid ${cols} gap-3`}>{children}</dl>
}
