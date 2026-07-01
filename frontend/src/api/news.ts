import client from './client'
import type {
  AblationEnqueueResponse,
  JobEnqueueResponse,
  NewsAblationRequest,
  NewsAnnotateRequest,
  NewsAnnotationSummary,
  NewsIngestRequest,
  NewsIngestionRunSummary,
} from '../types/news'

// Trigger endpoints return 202 with a queued job id; poll the audit rows /
// annotation summary until the work lands. Simulated research — not advice.
export async function triggerNewsIngest(
  req: NewsIngestRequest,
): Promise<JobEnqueueResponse> {
  const res = await client.post<JobEnqueueResponse>('/news/ingest', req)
  return res.data
}

export async function triggerNewsAnnotate(
  req: NewsAnnotateRequest,
): Promise<JobEnqueueResponse> {
  const res = await client.post<JobEnqueueResponse>('/news/annotate', req)
  return res.data
}

export async function triggerNewsAblation(
  req: NewsAblationRequest,
): Promise<AblationEnqueueResponse> {
  const res = await client.post<AblationEnqueueResponse>('/news/ablation', req)
  return res.data
}

export async function listNewsIngestionRuns(): Promise<NewsIngestionRunSummary[]> {
  const res = await client.get<NewsIngestionRunSummary[]>('/news/ingestion')
  return res.data
}

export async function getNewsAnnotationSummary(): Promise<NewsAnnotationSummary> {
  const res = await client.get<NewsAnnotationSummary>('/news/annotations/summary')
  return res.data
}
