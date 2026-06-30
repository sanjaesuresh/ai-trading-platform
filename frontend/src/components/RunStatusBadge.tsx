interface RunStatusBadgeProps {
  status: string
}

const CONFIG: Record<string, { label: string; cls: string }> = {
  queued: {
    label: 'Queued',
    cls: 'bg-raised text-ink-muted border border-edge',
  },
  completed: {
    label: 'Completed',
    cls: 'bg-positive/10 text-positive border border-positive/30',
  },
  failed: {
    label: 'Failed',
    cls: 'bg-negative/10 text-negative border border-negative/30',
  },
  running: {
    label: 'Running',
    cls: 'bg-caution/10 text-caution border border-caution/30 motion-safe:animate-pulse',
  },
  active: {
    label: 'Active',
    cls: 'bg-positive/10 text-positive border border-positive/30',
  },
  halted: {
    label: 'Halted',
    cls: 'bg-negative/10 text-negative border border-negative/30',
  },
}

export function RunStatusBadge({ status }: RunStatusBadgeProps) {
  const key = status.toLowerCase()
  const { label, cls } = CONFIG[key] ?? {
    label: status,
    cls: 'bg-raised text-ink-muted border border-edge',
  }
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-mono font-medium ${cls}`}>
      {label}
    </span>
  )
}
