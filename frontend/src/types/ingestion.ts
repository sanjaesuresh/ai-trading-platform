// Ingestion types — mirror the backend ingestion trigger + audit contracts (M6).

export interface IngestionRunRequest {
  mode: 'backfill' | 'incremental'
  // Omit / null to use the configured universe.
  symbols?: string[] | null
}

export interface IngestionEnqueueResponse {
  job_id: string | null
  status: string
  mode: string
  symbols: string[] | null
}

export interface IngestionRunSummary {
  id: number
  provider: string
  symbol: string
  range_start: string | null
  range_end: string | null
  rows_fetched: number | null
  rows_written: number | null
  status: string // queued | running | completed | failed
  error: string | null
  created_at: string
  finished_at: string | null
}
