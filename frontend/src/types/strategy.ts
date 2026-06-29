// Strategy discovery types (GET /strategies). The param form renders directly
// from `params_schema`, a JSON Schema produced by each strategy's param model,
// so adding a strategy needs no frontend change.

export interface JsonSchemaProperty {
  type?: string
  title?: string
  description?: string
  default?: number | string | boolean | null
  minimum?: number
  maximum?: number
  exclusiveMinimum?: number
  exclusiveMaximum?: number
}

export interface ParamsSchema {
  properties?: Record<string, JsonSchemaProperty>
  required?: string[]
  [key: string]: unknown
}

export interface StrategyInfo {
  name: string
  params_schema: ParamsSchema
}
