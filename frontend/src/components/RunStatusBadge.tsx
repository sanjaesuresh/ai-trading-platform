interface RunStatusBadgeProps {
  status: string
}

const CONFIG: Record<string, { label: string; cls: string }> = {
  queued: {
    label: 'Queued',
    cls: 'bg-slate-800 text-slate-300 border border-slate-600',
  },
  completed: {
    label: 'Completed',
    cls: 'bg-emerald-950 text-emerald-400 border border-emerald-800',
  },
  failed: {
    label: 'Failed',
    cls: 'bg-rose-950 text-rose-400 border border-rose-800',
  },
  running: {
    label: 'Running',
    cls: 'bg-amber-950 text-amber-400 border border-amber-800 motion-safe:animate-pulse',
  },
  active: {
    label: 'Active',
    cls: 'bg-emerald-950 text-emerald-400 border border-emerald-800',
  },
  halted: {
    label: 'Halted',
    cls: 'bg-rose-950 text-rose-400 border border-rose-800',
  },
}

export function RunStatusBadge({ status }: RunStatusBadgeProps) {
  const key = status.toLowerCase()
  const { label, cls } = CONFIG[key] ?? {
    label: status,
    cls: 'bg-zinc-800 text-zinc-400 border border-zinc-700',
  }
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-mono font-medium ${cls}`}>
      {label}
    </span>
  )
}
