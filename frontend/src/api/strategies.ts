import client from './client'
import type { StrategyInfo } from '../types/strategy'

export async function getStrategies(): Promise<StrategyInfo[]> {
  const res = await client.get<StrategyInfo[]>('/strategies')
  return res.data
}
