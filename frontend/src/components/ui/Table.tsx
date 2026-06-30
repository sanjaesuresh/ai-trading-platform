import type { ReactNode } from 'react'

interface TableProps {
  children: ReactNode
  /** Cap height and make the header sticky for long tables. */
  maxHeight?: string
}

/** Horizontally scrollable table shell with consistent type and density. */
export function Table({ children, maxHeight }: TableProps) {
  return (
    <div
      className="overflow-x-auto"
      style={maxHeight ? { maxHeight, overflowY: 'auto' } : undefined}
    >
      <table className="w-full text-sm border-collapse">{children}</table>
    </div>
  )
}

type Align = 'left' | 'right'

interface ThProps {
  children: ReactNode
  align?: Align
  /** Tiny second line under the header — typically a unit (e.g. "%", "USD"). */
  sub?: ReactNode
  /** Keep the header visible while the body scrolls (needs Table maxHeight). */
  sticky?: boolean
  /** Extra Tailwind classes (e.g. "sticky left-0 bg-zinc-900 z-20" for a frozen first column). */
  className?: string
}

const alignClass = (a: Align) => (a === 'right' ? 'text-right' : 'text-left')

export function Th({ children, align = 'left', sub, sticky, className = '' }: ThProps) {
  return (
    <th
      scope="col"
      className={`px-3 first:pl-0 last:pr-0 pb-2 align-bottom whitespace-nowrap text-[11px] font-medium text-zinc-500 uppercase tracking-wider ${alignClass(
        align,
      )} ${sticky ? 'sticky top-0 bg-zinc-950 z-10' : ''} ${className}`}
    >
      {children}
      {sub !== undefined && (
        <span className="block text-[10px] font-normal normal-case tracking-normal text-zinc-600">
          {sub}
        </span>
      )}
    </th>
  )
}

interface TdProps {
  children: ReactNode
  align?: Align
  /** Monospace tabular figures — use for every numeric cell. */
  mono?: boolean
  className?: string
  colSpan?: number
}

export function Td({ children, align = 'left', mono, className = '', colSpan }: TdProps) {
  return (
    <td
      colSpan={colSpan}
      className={`px-3 first:pl-0 last:pr-0 py-2.5 ${alignClass(align)} ${
        mono ? 'font-mono text-xs' : 'text-sm'
      } ${className}`}
    >
      {children}
    </td>
  )
}
