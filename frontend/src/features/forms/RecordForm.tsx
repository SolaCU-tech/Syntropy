import { zodResolver } from '@hookform/resolvers/zod'
import { Check, Loader2, Plus, Search, X } from 'lucide-react'
import { useId, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { Controller, useForm, type Control, type FieldErrors } from 'react-hook-form'

import { Button } from '@/components/ui/button'
import { Input, Label, Select, Textarea } from '@/components/ui/field'
import { useTitles } from '@/features/records/useTitles'
import { useWorkspace } from '@/features/workspace/context'
import { formSchema, toFormValues, type FormValues } from '@/lib/form-schema'
import { todayISO } from '@/lib/format'
import { relationshipFor, singularLabel, tableById, type FieldDef, type SSD, type Table, type Values } from '@/lib/ssd'
import { cn } from '@/lib/utils'

import { saveRecord, type SaveOutcome } from './save'

/**
 * The generated default form for a table (spec sections 10 and 18): typed widgets, required
 * markers, range and option checks, link pickers that can create a linked record inline, and
 * server errors shown on the right field. Validation is the same online and offline.
 */
export function RecordForm({
  ssd,
  table,
  initial,
  prefill,
  onSubmit,
  submitLabel = 'Save',
  onCancel,
  compact = false,
}: {
  ssd: SSD
  table: Table
  /** Existing values for an edit; omitted for a new record (defaults apply, dates default to today). */
  initial?: Values
  /** Starting values for a new record, e.g. the customer when adding "New sale for Adaeze". */
  prefill?: Values
  onSubmit: (values: Values) => Promise<unknown>
  submitLabel?: string
  onCancel?: () => void
  compact?: boolean
}) {
  const defaults = useMemo(() => {
    const values = toFormValues(table, initial)
    if (!initial) {
      for (const f of table.fields) {
        if (f.type === 'date' && f.display_role === 'date' && !values[f.id]) values[f.id] = todayISO()
        if (prefill && typeof prefill[f.id] === 'string') values[f.id] = prefill[f.id] as string
      }
    }
    return values
  }, [table, initial, prefill])

  const form = useForm<FormValues, unknown, Values>({ resolver: zodResolver(formSchema(table)), defaultValues: defaults })
  const [formError, setFormError] = useState<string | null>(null)

  const submit = form.handleSubmit(async (values) => {
    setFormError(null)
    const outcome = (await onSubmit(values)) as SaveOutcome | undefined
    if (outcome?.kind === 'invalid') {
      setFormError(outcome.message)
      for (const [fieldId, messages] of Object.entries(outcome.details)) {
        if (table.fields.some((f) => f.id === fieldId)) form.setError(fieldId, { type: 'server', message: messages.join(' ') })
      }
    }
  })

  return (
    <form
      onSubmit={(event) => {
        // An inline form (a new customer inside a sale) must not submit the form around it.
        event.stopPropagation()
        void submit(event)
      }}
      noValidate className="flex flex-col gap-5" aria-label={`${singularLabel(table)} form`}>
      <div className={cn('grid gap-5', !compact && 'sm:grid-cols-2')}>
        {table.fields.map((field) => (
          <FieldInput key={field.id} ssd={ssd} field={field} control={form.control} errors={form.formState.errors} />
        ))}
      </div>
      {formError && (
        <p role="alert" className="rounded-md bg-danger/10 px-3 py-2 text-sm text-danger">
          {formError}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" size="lg" disabled={form.formState.isSubmitting}>
          {form.formState.isSubmitting ? <Loader2 className="animate-spin" /> : <Check />} {submitLabel}
        </Button>
        {onCancel && (
          <Button type="button" size="lg" variant="outline" onClick={onCancel}>
            Cancel
          </Button>
        )}
      </div>
    </form>
  )
}

function FieldInput({
  ssd,
  field,
  control,
  errors,
}: {
  ssd: SSD
  field: FieldDef
  control: Control<FormValues, unknown, Values>
  errors: FieldErrors<FormValues>
}) {
  const id = useId()
  const error = errors[field.id]?.message as string | undefined
  const describedBy = [field.description ? `${id}-help` : null, error ? `${id}-error` : null].filter(Boolean).join(' ') || undefined
  const wide = field.type === 'text' && (field.max_length ?? 10_000) > 255

  return (
    <div className={cn('flex flex-col gap-1.5', wide && 'sm:col-span-2')}>
      {field.type !== 'boolean' && (
        <Label htmlFor={id}>
          {field.label}
          {field.required && (
            <span className="text-danger" aria-hidden="true">
              {' '}
              *
            </span>
          )}
          {field.required && <span className="sr-only"> (required)</span>}
        </Label>
      )}
      <Controller
        name={field.id}
        control={control}
        render={({ field: input }) => {
          const common = {
            id,
            name: input.name,
            onBlur: input.onBlur,
            ref: input.ref,
            'aria-invalid': error ? true : undefined,
            'aria-describedby': describedBy,
            'aria-required': field.required || undefined,
          }
          const text = String(input.value ?? '')
          switch (field.type) {
            case 'boolean':
              return (
                <label className="flex h-11 items-center gap-3 text-sm font-medium sm:h-9">
                  <input
                    type="checkbox"
                    className="size-5 accent-[var(--syn-primary)]"
                    {...common}
                    checked={input.value === true}
                    onChange={(e) => input.onChange(e.target.checked)}
                  />
                  {field.label}
                </label>
              )
            case 'enum':
              return (
                <Select {...common} value={text} onChange={(e) => input.onChange(e.target.value)}>
                  <option value="">{field.required ? 'Choose…' : 'None'}</option>
                  {field.options?.map((o) => (
                    <option key={o.key} value={o.key}>
                      {o.label}
                    </option>
                  ))}
                </Select>
              )
            case 'reference':
              return <LinkPicker ssd={ssd} field={field} value={text} onChange={input.onChange} inputProps={common} />
            case 'date':
              return <Input {...common} type="date" value={text} onChange={(e) => input.onChange(e.target.value)} />
            case 'datetime':
              return <Input {...common} type="datetime-local" value={text} onChange={(e) => input.onChange(e.target.value)} />
            case 'integer':
            case 'decimal': {
              const money = field.currency === 'NGN' ? '₦' : field.currency
              return (
                <div className="relative">
                  {money && (
                    <span className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-text-secondary">{money}</span>
                  )}
                  <Input
                    {...common}
                    inputMode={field.type === 'integer' ? 'numeric' : 'decimal'}
                    autoComplete="off"
                    className={cn('tabular', money && (money.length > 1 ? 'pl-12' : 'pl-7'))}
                    value={text}
                    onChange={(e) => input.onChange(e.target.value)}
                  />
                </div>
              )
            }
            default:
              return wide ? (
                <Textarea {...common} value={text} onChange={(e) => input.onChange(e.target.value)} />
              ) : (
                <Input {...common} value={text} onChange={(e) => input.onChange(e.target.value)} />
              )
          }
        }}
      />
      {field.description && (
        <p id={`${id}-help`} className="text-xs text-text-secondary">
          {field.description}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="text-xs text-danger">
          {error}
        </p>
      )}
    </div>
  )
}

/**
 * Search-as-you-type link picker over the cached title list (works offline), with
 * "New <customer>" to create the linked record inline (spec section 18, Forms).
 */
function LinkPicker({
  ssd,
  field,
  value,
  onChange,
  inputProps,
}: {
  ssd: SSD
  field: FieldDef
  value: string
  onChange: (value: string) => void
  inputProps: Record<string, unknown>
}) {
  const { workspace, schemaVersion } = useWorkspace()
  const rel = relationshipFor(ssd, field.id)
  const target = rel ? tableById(ssd, rel.to_table) : undefined
  const titles = useTitles(rel?.to_table)
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const listId = useId()

  if (!target) return <Input disabled value="" />
  const selectedTitle = value ? titles.get(value) : undefined
  const needle = query.trim().toLowerCase()
  const matches = [...titles.entries()]
    .filter(([, title]) => !needle || title.toLowerCase().includes(needle))
    .sort((a, b) => a[1].localeCompare(b[1]))
    .slice(0, 8)

  const creator = creating
    ? createPortal(
        <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center" role="dialog" aria-modal="true" aria-labelledby={`${listId}-title`}>
          <button type="button" className="absolute inset-0 bg-ink/40" aria-label="Close" onClick={() => setCreating(false)} />
          <div className="relative max-h-[90dvh] w-full overflow-y-auto rounded-t-xl bg-surface p-5 shadow-md sm:max-w-lg sm:rounded-xl">
            <p id={`${listId}-title`} className="mb-4 text-lg font-semibold">
              New {singularLabel(target).toLowerCase()}
            </p>
            <RecordForm
              ssd={ssd}
              table={target}
              compact
              submitLabel={`Add ${singularLabel(target).toLowerCase()}`}
              onCancel={() => setCreating(false)}
              onSubmit={async (values) => {
                const outcome = await saveRecord({ workspaceId: workspace.id, tableId: target.id, schemaVersion, values })
                if (outcome.kind === 'saved' || outcome.kind === 'queued') {
                  onChange(outcome.recordId)
                  setCreating(false)
                  setOpen(false)
                }
                return outcome
              }}
            />
          </div>
        </div>,
        document.body,
      )
    : null

  if (value && !open) {
    return (
      <div className="flex items-center gap-2">
        {creator}
        <span
          className="flex h-11 flex-1 items-center truncate rounded-md border bg-secondary px-3 font-medium text-primary sm:h-9"
          data-testid={`picked-${field.key}`}
        >
          {selectedTitle ?? 'Selected record'}
        </span>
        <Button type="button" variant="outline" size="icon" aria-label={`Change ${field.label}`} onClick={() => setOpen(true)}>
          <Search />
        </Button>
        {!field.required && (
          <Button type="button" variant="ghost" size="icon" aria-label={`Clear ${field.label}`} onClick={() => onChange('')}>
            <X />
          </Button>
        )}
      </div>
    )
  }

  return (
    <div className="relative">
      {creator}
      <Input
        {...inputProps}
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        placeholder={`Search ${target.label.toLowerCase()}`}
        value={query}
        onFocus={() => setOpen(true)}
        onChange={(e) => {
          setQuery(e.target.value)
          setOpen(true)
        }}
        onKeyDown={(e) => {
          if (e.key === 'Escape') setOpen(false)
          if (e.key === 'Enter') {
            e.preventDefault()
            if (matches[0]) {
              onChange(matches[0][0])
              setOpen(false)
              setQuery('')
            }
          }
        }}
      />
      {open && (
        <ul id={listId} role="listbox" className="absolute z-20 mt-1 max-h-72 w-full overflow-y-auto rounded-md border bg-surface p-1 shadow-md">
          {matches.map(([id, title]) => (
            <li key={id} role="none">
              <button
                type="button"
                role="option"
                aria-selected={id === value}
                className="flex h-10 w-full items-center rounded px-2 text-left hover:bg-secondary"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => {
                  onChange(id)
                  setOpen(false)
                  setQuery('')
                }}
              >
                {title}
              </button>
            </li>
          ))}
          {matches.length === 0 && (
            <li role="none" className="px-2 py-2 text-text-secondary">
              No matches
            </li>
          )}
          <li role="none">
            <button
              type="button"
              role="option"
              aria-selected={false}
              className="flex h-10 w-full items-center gap-2 rounded px-2 text-left font-medium text-primary hover:bg-secondary"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => {
                setCreating(true)
                setOpen(false)
              }}
            >
              <Plus className="size-4" /> New {singularLabel(target).toLowerCase()}
              {query && ` “${query}”`}
            </button>
          </li>
        </ul>
      )}
    </div>
  )
}
