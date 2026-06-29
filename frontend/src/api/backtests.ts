import client from './client'
import type { RunRequest, RunSummary, RunDetail } from '../types/backtest'

export async function listRuns(): Promise<RunSummary[]> {
  const res = await client.get<RunSummary[]>('/backtests')
  return res.data
}

export async function getRun(id: number): Promise<RunDetail> {
  const res = await client.get<RunDetail>(`/backtests/${id}`)
  return res.data
}

export async function runBacktest(req: RunRequest): Promise<RunSummary> {
  const res = await client.post<RunSummary>('/backtests/run', req)
  return res.data
}
