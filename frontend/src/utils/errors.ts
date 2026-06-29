import axios from 'axios'

export function isNotFound(err: unknown): boolean {
  return axios.isAxiosError(err) && err.response?.status === 404
}

export function extractMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const data: unknown = err.response?.data
    if (typeof data === 'object' && data !== null) {
      const detail = (data as Record<string, unknown>)['detail']
      if (typeof detail === 'object' && detail !== null) {
        const msg = (detail as Record<string, unknown>)['message']
        if (typeof msg === 'string' && msg.length > 0) return msg
      }
      if (typeof detail === 'string' && detail.length > 0) return detail
    }
    if (err.response?.status === 404) return 'Not found.'
    return err.message || 'Request failed.'
  }
  if (err instanceof Error) return err.message
  return 'An unexpected error occurred.'
}
