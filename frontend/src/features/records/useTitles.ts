import { useLookup, useQueue } from '@/api/hooks'
import { useWorkspace } from '@/features/workspace/context'
import { recordTitle, tableById } from '@/lib/ssd'

/** Record titles for a table: the cached lookup plus records created on this device. */
export function useTitles(tableId: string | undefined): Map<string, string> {
  const { workspace, ssd } = useWorkspace()
  const lookup = useLookup(workspace.id, tableId ?? '')
  const queue = useQueue(workspace.id)
  const titles = new Map<string, string>()
  const table = ssd && tableId ? tableById(ssd, tableId) : undefined
  for (const item of lookup.data ?? []) {
    titles.set(item.id, item.title ?? (table ? recordTitle(table, {}, item.id) : item.id))
  }
  if (table) {
    for (const op of queue) {
      if (op.table_id !== tableId) continue
      const existing = titles.get(op.record_id)
      if (op.op === 'create' || !existing) titles.set(op.record_id, recordTitle(table, op.values, op.record_id))
      else titles.set(op.record_id, recordTitle(table, { [table.fields[0].id]: existing, ...op.values }, op.record_id))
    }
  }
  return titles
}
