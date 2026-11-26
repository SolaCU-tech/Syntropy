import { Link } from 'react-router'

import { Badge } from '@/components/ui/field'
import { formatValue, isNumeric } from '@/lib/format'
import { relationshipFor, tableById, type FieldDef, type SSD } from '@/lib/ssd'
import { cn } from '@/lib/utils'
import { useWorkspace } from '@/features/workspace/context'

import { useTitles } from './useTitles'

const statusTones = ['primary', 'success', 'warning', 'gold', 'neutral', 'danger'] as const

/** One typed value: money right-aligned with tabular figures, enums as pills, links as chips. */
export function FieldValue({ field, value, ssd }: { field: FieldDef; value: unknown; ssd: SSD }) {
  if (field.type === 'reference') return <LinkChip field={field} value={value} ssd={ssd} />
  if (value === null || value === undefined || value === '') return <span className="text-text-muted">—</span>
  if (field.type === 'enum') {
    const index = Math.max(0, field.options?.findIndex((o) => o.key === value) ?? 0)
    const tone = field.display_role === 'status' ? statusTones[index % statusTones.length] : 'neutral'
    return <Badge tone={tone}>{formatValue(field, value)}</Badge>
  }
  return <span className={cn(isNumeric(field) && 'tabular')}>{formatValue(field, value)}</span>
}

function LinkChip({ field, value, ssd }: { field: FieldDef; value: unknown; ssd: SSD }) {
  const { workspace } = useWorkspace()
  const rel = relationshipFor(ssd, field.id)
  const target = rel ? tableById(ssd, rel.to_table) : undefined
  const titles = useTitles(rel?.to_table)
  if (typeof value !== 'string' || !target) return <span className="text-text-muted">—</span>
  return (
    <Link
      to={`/w/${workspace.slug}/tables/${target.key}/${value}`}
      onClick={(e) => e.stopPropagation()}
      className="inline-flex max-w-48 items-center truncate rounded-md bg-secondary px-2 py-0.5 text-xs font-medium text-primary hover:underline"
    >
      {titles.get(value) ?? `${target.label.replace(/s$/, '')} ${value.slice(-6)}`}
    </Link>
  )
}
