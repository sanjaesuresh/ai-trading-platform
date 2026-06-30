import {
  useId,
  useState,
  useRef,
  useEffect,
  useCallback,
  type ReactNode,
} from 'react'
import { createPortal } from 'react-dom'
import { GLOSSARY, type GlossaryId } from '../../lib/glossary'

interface InfoTipProps {
  /** Term name, used in the tooltip heading and the screen-reader label. */
  label: string
  /** Plain-English definition shown in the bubble. */
  definition: ReactNode
  /** Optional visible trigger text rendered before the marker (e.g. the term). */
  children?: ReactNode
}

const BUBBLE_W = 256 // matches w-64
const MARGIN = 8

/**
 * An accessible inline definition marker. Renders a small "i" button; the
 * definition appears on hover, on keyboard focus, and on tap, and dismisses on
 * Escape, click-away, or scroll. The bubble is rendered in a portal with fixed
 * positioning so it is never clipped by a scrolling table, and a short close
 * delay lets the pointer travel from the marker into the bubble without it
 * vanishing. Wired with aria-label + aria-describedby + role="tooltip"; color is
 * never the only signal.
 */
export function InfoTip({ label, definition, children }: InfoTipProps) {
  const id = useId()
  const [open, setOpen] = useState(false)
  const [coords, setCoords] = useState<{ top: number; left: number }>({ top: 0, left: 0 })
  const btnRef = useRef<HTMLButtonElement>(null)
  const bubbleRef = useRef<HTMLSpanElement>(null)
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const place = useCallback(() => {
    const el = btnRef.current
    if (!el) return
    const r = el.getBoundingClientRect()
    const left = Math.max(
      MARGIN,
      Math.min(r.left, window.innerWidth - BUBBLE_W - MARGIN),
    )
    setCoords({ top: r.bottom + 6, left })
  }, [])

  const show = useCallback(() => {
    if (closeTimer.current) clearTimeout(closeTimer.current)
    place()
    setOpen(true)
  }, [place])

  const hideSoon = useCallback(() => {
    if (closeTimer.current) clearTimeout(closeTimer.current)
    closeTimer.current = setTimeout(() => setOpen(false), 120)
  }, [])

  useEffect(() => {
    if (!open) return
    function onDocDown(e: MouseEvent) {
      const t = e.target as Node
      if (
        !btnRef.current?.contains(t) &&
        !bubbleRef.current?.contains(t)
      ) {
        setOpen(false)
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    function onScroll() {
      setOpen(false)
    }
    document.addEventListener('mousedown', onDocDown)
    document.addEventListener('keydown', onKey)
    window.addEventListener('scroll', onScroll, true)
    window.addEventListener('resize', onScroll)
    return () => {
      document.removeEventListener('mousedown', onDocDown)
      document.removeEventListener('keydown', onKey)
      window.removeEventListener('scroll', onScroll, true)
      window.removeEventListener('resize', onScroll)
    }
  }, [open])

  return (
    <span className="inline-flex items-center gap-1 align-baseline">
      {children}
      <button
        ref={btnRef}
        type="button"
        aria-label={`What is ${label}?`}
        aria-expanded={open}
        aria-describedby={open ? id : undefined}
        onClick={() => (open ? setOpen(false) : show())}
        onMouseEnter={show}
        onMouseLeave={hideSoon}
        onFocus={show}
        onBlur={() => setOpen(false)}
        className="inline-grid place-items-center h-6 w-6 -my-1 shrink-0 rounded-full text-ink-subtle transition-colors hover:text-accent focus-visible:text-accent"
      >
        <span
          aria-hidden
          className="grid h-[15px] w-[15px] place-items-center rounded-full border border-current text-[10px] font-semibold leading-none"
        >
          i
        </span>
      </button>
      {open &&
        createPortal(
          <span
            ref={bubbleRef}
            role="tooltip"
            id={id}
            onMouseEnter={show}
            onMouseLeave={hideSoon}
            style={{ position: 'fixed', top: coords.top, left: coords.left, width: BUBBLE_W }}
            className="z-50 block rounded-lg border border-edge bg-raised p-3 text-left shadow-raised normal-case"
          >
            <span className="block text-[11px] font-semibold text-ink mb-1">
              {label}
            </span>
            <span className="block text-xs leading-snug text-ink-muted font-normal tracking-normal">
              {definition}
            </span>
          </span>,
          document.body,
        )}
    </span>
  )
}

interface TermProps {
  /** Glossary key to pull the term + definition from. */
  id: GlossaryId
  /** Render the term text before the marker. Default true. */
  withLabel?: boolean
  /** Override the visible text (still uses the glossary definition). */
  children?: ReactNode
}

/**
 * Convenience wrapper: look a term up in the shared glossary and render it as an
 * InfoTip. Use <Term id="sharpe_ratio" /> inline in prose, or
 * <Term id="sharpe_ratio" withLabel={false} /> to attach just the marker to an
 * existing label.
 */
export function Term({ id, withLabel = true, children }: TermProps) {
  const entry = GLOSSARY[id]
  return (
    <InfoTip label={entry.term} definition={entry.definition}>
      {withLabel ? <span>{children ?? entry.term}</span> : null}
    </InfoTip>
  )
}
