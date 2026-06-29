import client from './client'
import type {
  IngestionEnqueueResponse,
  IngestionRunRequest,
  IngestionRunSummary,
} from '../types/ingestion'

// Enqueues a background ingest; returns 202 with the queued job id. Watch the
// audit rows via listIngestionRuns / getIngestionRun.
export async function triggerIngestion(
  req: IngestionRunRequest,
): Promise<IngestionEnqueueResponse> {
  const res = await client.post<IngestionEnqueueResponse>('/ingestion/run', req)
  return res.data
}

export async function listIngestionRuns(): Promise<IngestionRunSummary[]> {
  const res = await client.get<IngestionRunSummary[]>('/ingestion')
  return res.data
}

export async function getIngestionRun(id: number): Promise<IngestionRunSummary> {
  const res = await client.get<IngestionRunSummary>(`/ingestion/${id}`)
  return res.data
}
