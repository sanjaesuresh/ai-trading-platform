import type { ParamsSchema } from '../types/strategy'
import { Field, inputClass } from './ui'

interface StrategyParamFieldsProps {
  schema: ParamsSchema
  values: Record<string, number>
  onChange: (values: Record<string, number>) => void
}

// Pre-fill one value per numeric property from its JSON-Schema default, so the
// form is usable the moment a strategy is picked. Adding a strategy needs no
// frontend change — the inputs come straight from its param schema.
export function defaultsFromSchema(schema: ParamsSchema): Record<string, number> {
  const out: Record<string, number> = {}
  for (const [key, prop] of Object.entries(schema.properties ?? {})) {
    if (typeof prop.default === 'number') out[key] = prop.default
  }
  return out
}

function labelFor(key: string, title?: string): string {
  if (title && title.length > 0) return title
  return key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function rangeHint(min: number | undefined, max: number | undefined): string | null {
  if (min !== undefined && max !== undefined) return `Range ${min}–${max}`
  if (min !== undefined) return `Min ${min}`
  if (max !== undefined) return `Max ${max}`
  return null
}

export function StrategyParamFields({
  schema,
  values,
  onChange,
}: StrategyParamFieldsProps) {
  const properties = Object.entries(schema.properties ?? {})

  if (properties.length === 0) {
    return (
      <p className="text-sm text-ink-subtle">This strategy has no tunable parameters.</p>
    )
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
      {properties.map(([key, prop]) => {
        const min = prop.minimum ?? prop.exclusiveMinimum
        const max = prop.maximum ?? prop.exclusiveMaximum
        const value = values[key]
        const inputId = `param-${key}`
        const range = rangeHint(min, max)
        const hint = [prop.description, range].filter(Boolean).join(' · ')
        return (
          <Field
            key={key}
            label={labelFor(key, prop.title)}
            htmlFor={inputId}
            hint={hint.length > 0 ? hint : undefined}
          >
            <input
              id={inputId}
              type="number"
              step="any"
              min={min}
              max={max}
              value={value ?? ''}
              onChange={(e) => {
                const next = e.target.value
                onChange({
                  ...values,
                  [key]: next === '' ? Number.NaN : Number(next),
                })
              }}
              className={inputClass}
            />
          </Field>
        )
      })}
    </div>
  )
}
