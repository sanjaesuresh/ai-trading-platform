import type { ReactNode } from 'react'

export interface ProvenanceItem {
  label: string
  value: ReactNode
}

interface ProvenanceStripProps {
  items: ProvenanceItem[]
}

/**
 * Compact metadata line for detail pages — what you are looking at and how it
 * was produced (symbol, strategy, date range, bar count, simulated marker).
 * Each item is a label/value pair; falsy values are dropped.
 */
export function ProvenanceStrip({ items }: ProvenanceStripProps) {
  const shown = items.filter((i) => i.value !== null && i.value !== undefined && i.value !== '')
  if (shown.length === 0) return null

  return (
    <dl className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded border border-zinc-800 bg-zinc-900 px-4 py-2.5">
      {shown.map((item) => (
        <div key={item.label} className="flex items-baseline gap-1.5">
          <dt className="text-[11px] uppercase tracking-wider text-zinc-600">
            {item.label}
          </dt>
          <dd className="font-mono text-xs text-zinc-300">{item.value}</dd>
        </div>
      ))}
    </dl>
  )
}
