import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

interface PageHeaderProps {
  title: ReactNode
  /** One-line description of what this page is for. */
  subtitle?: ReactNode
  /** Optional right-aligned slot: counts, primary action, status. */
  meta?: ReactNode
  /** Optional back link rendered above the title. */
  back?: { to: string; label: string }
}

/** Standard page heading: optional back link, title, and a clarifying subtitle. */
export function PageHeader({ title, subtitle, meta, back }: PageHeaderProps) {
  return (
    <div>
      {back && (
        <Link
          to={back.to}
          className="inline-block text-xs text-ink-subtle hover:text-accent transition-colors mb-2"
        >
          ← {back.label}
        </Link>
      )}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-ink">{title}</h1>
          {subtitle !== undefined && (
            <p className="text-sm text-ink-muted mt-1 max-w-2xl">{subtitle}</p>
          )}
        </div>
        {meta !== undefined && <div className="shrink-0">{meta}</div>}
      </div>
    </div>
  )
}
