import axios from 'axios'

export function isNotFound(err: unknown): boolean {
  return axios.isAxiosError(err) && err.response?.status === 404
}

export function extractMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const data: unknown = err.response?.data
    if (typeof data === 'object' && data !== null) {
      const detail = (data as Record<string, unknown>)['detail']

      // App errors: { detail: { message, errors: [...] } } — surface both the
      // headline and the data-quality error list rather than just the headline.
      if (typeof detail === 'object' && detail !== null && !Array.isArray(detail)) {
        const d = detail as Record<string, unknown>
        const msg = typeof d['message'] === 'string' ? d['message'] : ''
        const errors = Array.isArray(d['errors'])
          ? d['errors'].filter((e): e is string => typeof e === 'string')
          : []
        const parts = [msg, ...errors].filter((p) => p.length > 0)
        if (parts.length > 0) return parts.join(' ')
      }

      // FastAPI request-validation errors: { detail: [ { msg, loc, ... } ] }.
      if (Array.isArray(detail)) {
        const msgs = detail
          .map((item) =>
            typeof item === 'object' &&
            item !== null &&
            typeof (item as Record<string, unknown>)['msg'] === 'string'
              ? ((item as Record<string, unknown>)['msg'] as string)
              : '',
          )
          .filter((m) => m.length > 0)
        if (msgs.length > 0) return msgs.join('; ')
      }

      if (typeof detail === 'string' && detail.length > 0) return detail
    }
    if (err.response?.status === 404) return 'Not found.'
    return err.message || 'Request failed.'
  }
  if (err instanceof Error) return err.message
  return 'An unexpected error occurred.'
}
