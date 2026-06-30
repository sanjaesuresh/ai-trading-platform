const USD = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

export function formatCurrency(value: number): string {
  return USD.format(value)
}

/** Format a value that is already in percent units (e.g. 15.3 → "15.30%"). */
export function formatPercent(value: number): string {
  return `${value.toFixed(2)}%`
}

/** Percent with an explicit sign (e.g. 15.3 → "+15.30%", -4 → "−4.00%"). */
export function formatSignedPercent(value: number): string {
  if (value > 0) return `+${value.toFixed(2)}%`
  if (value < 0) return `−${Math.abs(value).toFixed(2)}%`
  return `${value.toFixed(2)}%`
}

/** Format a 0..1 fraction as a percentage (e.g. 0.6 → "60.0%"). */
export function formatFraction(value: number): string {
  return `${(value * 100).toFixed(1)}%`
}

export function formatProfitFactor(value: number): string {
  if (!isFinite(value) || value >= 1e8) return '∞'
  return value.toFixed(2)
}

export function formatDate(isoString: string): string {
  return new Date(isoString).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

export function formatDateTime(isoString: string): string {
  return new Date(isoString).toLocaleString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** Tailwind color class for positive/zero/negative percent values. */
export function returnClass(value: number): string {
  if (value > 0) return 'text-emerald-400'
  if (value < 0) return 'text-rose-400'
  return 'text-zinc-50'
}
