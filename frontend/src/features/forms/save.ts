import { ApiError } from '@/api/client'
import { db } from '@/features/sync/db'
import { enqueueCreate, enqueueUpdate, newRecordId, syncNow } from '@/features/sync/queue'
import type { Values } from '@/lib/ssd'

export type SaveOutcome =
  | { kind: 'saved'; recordId: string }
  | { kind: 'queued'; recordId: string }
  | { kind: 'invalid'; recordId: string; message: string; details: Record<string, string[]> }
  | { kind: 'conflict'; recordId: string }

type Save = { workspaceId: string; tableId: string; schemaVersion: number; values: Values }

/**
 * Save through the queue (online or offline alike), then try to sync straight away.
 *
 * - applied: the server has it.
 * - still pending: the device is offline; it stays queued and syncs later.
 * - rejected or schema changed while online: the user is still on the form with their values,
 *   so the change is taken back out of the queue and the errors are shown on the form.
 * - conflict: stays queued for the user to choose on the Waiting to sync screen.
 */
export async function saveRecord(
  save: Save,
  edit?: { recordId: string; baseVersion: number },
): Promise<SaveOutcome> {
  const recordId = edit?.recordId ?? newRecordId()
  const op = edit
    ? await enqueueUpdate(save, edit.recordId, edit.baseVersion)
    : await enqueueCreate(save, recordId)
  try {
    await syncNow(save.workspaceId)
  } catch (error) {
    if (!(error instanceof ApiError)) throw error
  }
  const after = await db().queue.get(op.id!)
  if (!after) return { kind: 'saved', recordId }
  if (after.status === 'pending') return { kind: 'queued', recordId }
  if (after.status === 'conflict') return { kind: 'conflict', recordId }
  await db().queue.delete(after.id!)
  const details: Record<string, string[]> = {}
  for (const [key, value] of Object.entries(after.error?.details ?? {})) {
    details[key] = Array.isArray(value) ? value : [String(value)]
  }
  return { kind: 'invalid', recordId, message: after.error?.message ?? "We couldn't save that.", details }
}
