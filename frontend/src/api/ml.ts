// ML pipeline API client (Phase 4 M5).
// All results are simulated — not financial advice.
import client from './client'
import type {
  MLEvaluationDetail,
  MLEvaluationSummary,
  MLModelDetail,
  MLModelSummary,
  MLWalkForwardRequest,
} from '../types/ml'

export async function listMLModels(): Promise<MLModelSummary[]> {
  const res = await client.get<MLModelSummary[]>('/ml/models')
  return res.data
}

export async function getMLModel(modelId: string): Promise<MLModelDetail> {
  const res = await client.get<MLModelDetail>(`/ml/models/${modelId}`)
  return res.data
}

export async function runMLWalkForward(
  req: MLWalkForwardRequest,
): Promise<MLEvaluationSummary> {
  const res = await client.post<MLEvaluationSummary>(
    '/ml/evaluations/walk-forward',
    req,
  )
  return res.data
}

export async function getMLEvaluation(id: number): Promise<MLEvaluationDetail> {
  const res = await client.get<MLEvaluationDetail>(`/ml/evaluations/${id}`)
  return res.data
}
