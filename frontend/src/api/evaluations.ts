import client from './client'
import type {
  EvaluationDetail,
  EvaluationSummary,
  SweepRequest,
  WalkForwardRequest,
} from '../types/evaluation'

// Async by default: these return 202 with a `queued` summary; poll getEvaluation
// until the status is terminal. The `/sync` sub-paths run inline (small grids).
export async function runSweep(req: SweepRequest): Promise<EvaluationSummary> {
  const res = await client.post<EvaluationSummary>('/evaluations/sweep', req)
  return res.data
}

export async function runWalkForward(
  req: WalkForwardRequest,
): Promise<EvaluationSummary> {
  const res = await client.post<EvaluationSummary>('/evaluations/walk-forward', req)
  return res.data
}

export async function listEvaluations(): Promise<EvaluationSummary[]> {
  const res = await client.get<EvaluationSummary[]>('/evaluations')
  return res.data
}

export async function getEvaluation(id: number): Promise<EvaluationDetail> {
  const res = await client.get<EvaluationDetail>(`/evaluations/${id}`)
  return res.data
}
