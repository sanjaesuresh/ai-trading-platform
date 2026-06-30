import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

interface PageIntroProps {
  /** Big friendly page title. */
  title: ReactNode
  /** Plain-English "what is this and what do you do here". Can hold InfoTips. */
  children: ReactNode
  /** Small emoji/glyph shown in the accent tile beside the title. */
  icon?: ReactNode
  /** Tiny uppercase eyebrow above the title (e.g. the section name). */
  eyebrow?: string
  /** Right-aligned slot: counts, a primary action, a status control. */
  meta?: ReactNode
  /** Optional back link rendered above the title. */
  back?: { to: string; label: string }
}

/**
 * The welcoming page header. Every page opens with one of these: a clear title
 * and a short, plain-English explanation of what the page is for — so a
 * first-time visitor is never dropped into a wall of jargon. Replaces the older
 * terse PageHeader subtitle pattern.
 */
export function PageIntro({
  title,
  children,
  icon,
  eyebrow,
  meta,
  back,
}: PageIntroProps) {
  return (
    <section className="mb-8">
      {back && (
        <Link
          to={back.to}
          className="inline-flex items-center gap-1 text-xs text-ink-subtle hover:text-accent transition-colors mb-3"
        >
          <span aria-hidden>←</span> {back.label}
        </Link>
      )}
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3.5 min-w-0">
          {icon !== undefined && (
            <span
              aria-hidden
              className="shrink-0 mt-0.5 h-10 w-10 rounded-lg bg-accent/10 border border-accent/30 grid place-items-center text-lg"
            >
              {icon}
            </span>
          )}
          <div className="min-w-0">
            {eyebrow !== undefined && (
              <p className="text-[11px] font-semibold uppercase tracking-widest text-accent mb-1">
                {eyebrow}
              </p>
            )}
            <h1 className="text-2xl font-semibold text-ink tracking-tight">
              {title}
            </h1>
          </div>
        </div>
        {meta !== undefined && <div className="shrink-0">{meta}</div>}
      </div>
      <div className="mt-4 rounded-lg border border-hairline bg-surface/60 px-4 py-3 max-w-3xl">
        <p className="text-sm leading-relaxed text-ink-muted">{children}</p>
      </div>
    </section>
  )
}
