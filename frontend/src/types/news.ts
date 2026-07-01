// News types — mirror the backend news trigger + audit + ablation contracts (M7).

export interface NewsIngestRequest {
  mode: 'backfill' | 'incremental'
  symbols?: string[] | null
}

export interface NewsAnnotateRequest {
  phase: 'submit' | 'collect' | 'both'
}

export interface JobEnqueueResponse {
  job_id: string | null
  status: string
  detail: string
}

export interface NewsIngestionRunSummary {
  id: number
  provider: string
  symbol: string
  range_start: string | null
  range_end: string | null
  items_fetched: number | null
  items_written: number | null
  items_dropped: number | null
  status: string
  error: string | null
  created_at: string
  finished_at: string | null
}

export interface NewsAnnotationSummary {
  prompt_version: string
  total_annotations: number
  ok_annotations: number
  failed_annotations: number
  total_cost_usd: number
  pending_articles: number
}

export interface NewsAblationRequest {
  symbols: string[]
  eval_symbol: string
  n_news_configs_tried: number
}

export interface AblationEnqueueResponse {
  evaluation_run_id: number
  job_id: string | null
  status: string
}

// The AblationResult shape stored in EvaluationRun.results (read via getEvaluation).
export interface AblationArm {
  verdict: string
  reasons?: string[]
  significance?: {
    sharpe: number
    deflated_sharpe: number
    pbo: number
    mc_percentile: number
    n_config_trials: number
    n_oos_round_trips: number
  }
}

export interface AblationIncremental {
  mean_diff: number
  bootstrap_p_value: number
  deflated_sharpe: number
  n_obs: number
  n_trials: number
  beats_price_only: boolean
}

export interface AblationResult {
  eval_symbol: string
  price_arm: AblationArm
  news_arm: AblationArm
  price_n_trials: number
  news_n_trials: number
  n_news_configs_tried: number
  annotation_cost_usd: number
  daily_cost_drag: number
  cost_per_news_trade: number
  incremental: AblationIncremental
  n_paired_bars: number
  dsr_caveat: string
}
