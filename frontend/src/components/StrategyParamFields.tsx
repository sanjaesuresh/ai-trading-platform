import type { ParamsSchema } from '../types/strategy'

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

export function StrategyParamFields({
  schema,
  values,
  onChange,
}: StrategyParamFieldsProps) {
  const properties = Object.entries(schema.properties ?? {})

  if (properties.length === 0) {
    return (
      <p className="text-sm text-zinc-500">
        This strategy has no tunable parameters.
      </p>
    )
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
      {properties.map(([key, prop]) => {
        const min = prop.minimum ?? prop.exclusiveMinimum
        const max = prop.maximum ?? prop.exclusiveMaximum
        const value = values[key]
        const inputId = `param-${key}`
        return (
          <div key={key}>
            <label
              htmlFor={inputId}
              className="block text-xs text-zinc-400 font-medium mb-1"
            >
              {labelFor(key, prop.title)}
            </label>
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
              className="w-full bg-zinc-950 border border-zinc-700 rounded px-2 py-1.5 text-sm font-mono text-zinc-50 focus:border-amber-400 focus:outline-none"
            />
            {prop.description && (
              <p className="text-xs text-zinc-600 mt-1">{prop.description}</p>
            )}
          </div>
        )
      })}
    </div>
  )
}
