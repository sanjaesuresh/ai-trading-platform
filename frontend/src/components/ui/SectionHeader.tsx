import type { ReactNode } from 'react'

interface SectionHeaderProps {
  title: string
  /** One-line description of what this section shows. */
  subtitle?: ReactNode
  /** id for the heading, so a <section aria-labelledby> can reference it. */
  id?: string
  /** Optional right-aligned slot: a count, a control, a link. */
  right?: ReactNode
}

/** Uppercase micro section label with an optional clarifying subtitle. */
export function SectionHeader({ title, subtitle, id, right }: SectionHeaderProps) {
  return (
    <div className="mb-3 flex items-end justify-between gap-4">
      <div>
        <h2
          id={id}
          className="text-xs font-medium text-zinc-500 uppercase tracking-wider"
        >
          {title}
        </h2>
        {subtitle !== undefined && (
          <p className="text-xs text-zinc-600 mt-1 max-w-2xl">{subtitle}</p>
        )}
      </div>
      {right !== undefined && <div className="shrink-0">{right}</div>}
    </div>
  )
}
