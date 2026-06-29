import { useCallback, useEffect, useRef, useState } from 'react'

interface UsePollingOptions {
  // Keep polling while true (caller sets it from the job status, e.g.
  // status === 'queued' || status === 'running'); stop on a terminal status.
  active: boolean
  intervalMs?: number
}

interface UsePollingResult<T> {
  data: T | null
  error: unknown
  loading: boolean
  refetch: () => void
}

// Calls `fetcher` once on mount and then every `intervalMs` while `active`, and
// stops once `active` becomes false. A response that resolves after unmount (or
// after the deps changed) is ignored, so state is never set on a dead component.
export function usePolling<T>(
  fetcher: () => Promise<T>,
  { active, intervalMs = 2000 }: UsePollingOptions,
): UsePollingResult<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)
  const [tick, setTick] = useState(0)

  // Hold the latest fetcher in a ref so an inline closure doesn't restart the
  // interval on every render; the effect re-runs only on active/interval/refetch.
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  const refetch = useCallback(() => setTick((t) => t + 1), [])

  useEffect(() => {
    let cancelled = false

    const run = async () => {
      try {
        const result = await fetcherRef.current()
        if (!cancelled) {
          setData(result)
          setError(null)
        }
      } catch (err) {
        if (!cancelled) setError(err)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    run()
    const timer = active ? setInterval(run, intervalMs) : undefined

    return () => {
      cancelled = true
      if (timer) clearInterval(timer)
    }
  }, [active, intervalMs, tick])

  return { data, error, loading, refetch }
}
