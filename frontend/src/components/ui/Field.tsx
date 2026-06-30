import type { ReactNode } from 'react'

/** Shared input styling so every form control looks and focuses the same. */
export const inputClass =
  'w-full bg-zinc-950 border border-zinc-700 rounded px-2 py-1.5 text-sm font-mono text-zinc-50 focus:border-amber-400 focus:outline-none'

interface FieldProps {
  label: string
  htmlFor?: string
  /** Unit shown small next to the label (e.g. "bps", "%", "USD"). */
  unit?: string
  /** One-line helper under the control explaining what it does or a range. */
  hint?: ReactNode
  children: ReactNode
}

/** Labeled form field with an optional unit and a clarifying helper caption. */
export function Field({ label, htmlFor, unit, hint, children }: FieldProps) {
  return (
    <div>
      <label
        htmlFor={htmlFor}
        className="flex items-baseline justify-between gap-2 mb-1"
      >
        <span className="text-xs font-medium text-zinc-400">{label}</span>
        {unit !== undefined && (
          <span className="text-[11px] font-mono text-zinc-600">{unit}</span>
        )}
      </label>
      {children}
      {hint !== undefined && (
        <p className="mt-1 text-[11px] leading-snug text-zinc-600">{hint}</p>
      )}
    </div>
  )
}
