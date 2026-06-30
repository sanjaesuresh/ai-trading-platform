import client from './client'
import type {
  ComparisonView,
  DeploymentCreateRequest,
  DeploymentDetail,
  DeploymentSummary,
  KillSwitchStatus,
  PortfolioView,
  RunTriggerResponse,
} from '../types/paperTrading'

export async function listDeployments(): Promise<DeploymentSummary[]> {
  const res = await client.get<DeploymentSummary[]>('/paper/deployments')
  return res.data
}

export async function getDeployment(id: number): Promise<DeploymentDetail> {
  const res = await client.get<DeploymentDetail>(`/paper/deployments/${id}`)
  return res.data
}

export async function createDeployment(
  req: DeploymentCreateRequest,
): Promise<DeploymentDetail> {
  const res = await client.post<DeploymentDetail>('/paper/deployments', req)
  return res.data
}

export async function setDeploymentEnabled(
  id: number,
  enabled: boolean,
): Promise<DeploymentDetail> {
  const res = await client.post<DeploymentDetail>(
    `/paper/deployments/${id}/enable`,
    { enabled },
  )
  return res.data
}

export async function triggerRun(
  id: number,
  phase: 'submit' | 'reconcile' | 'both' = 'both',
): Promise<RunTriggerResponse> {
  const res = await client.post<RunTriggerResponse>(
    `/paper/deployments/${id}/run`,
    { phase },
  )
  return res.data
}

export async function getPortfolio(id: number): Promise<PortfolioView> {
  const res = await client.get<PortfolioView>(`/paper/deployments/${id}/portfolio`)
  return res.data
}

export async function getComparison(id: number): Promise<ComparisonView> {
  const res = await client.get<ComparisonView>(`/paper/deployments/${id}/comparison`)
  return res.data
}

export async function getKillSwitch(): Promise<KillSwitchStatus> {
  const res = await client.get<KillSwitchStatus>('/paper/kill-switch')
  return res.data
}

export async function setKillSwitch(
  active: boolean,
  reason = '',
): Promise<KillSwitchStatus> {
  const res = await client.post<KillSwitchStatus>('/paper/kill-switch', {
    active,
    reason,
  })
  return res.data
}
