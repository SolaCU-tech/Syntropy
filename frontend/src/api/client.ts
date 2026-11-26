import type { components } from './types'

export type Schemas = components['schemas']
export type Health = Schemas['Health']
export type Session = Schemas['Session']
export type Workspace = Schemas['Workspace']
export type ApiRecord = Schemas['Record']
export type RecordPage = Schemas['RecordPage']
export type TableSummary = Schemas['TableSummary']
export type LookupItem = Schemas['LookupItem']
export type SyncOperationRequest = Schemas['SyncOperationRequest']
export type SyncResponse = Schemas['SyncResponse']
export type SyncResult = Schemas['SyncResult']

/** Field-level messages keyed by field ID (or "non_field"), the API's one error shape. */
export type ErrorDetails = Record<string, string[] | string>

/** The server answered with an error (spec section 11: a code, a message, field details). */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: ErrorDetails
  readonly body: Record<string, unknown>

  constructor(status: number, body: Record<string, unknown>) {
    super(typeof body.message === 'string' ? body.message : `Request failed (${status})`)
    this.status = status
    this.code = typeof body.code === 'string' ? body.code : 'error'
    this.details = (body.details as ErrorDetails | undefined) ?? {}
    this.body = body
  }
}

/** The request never reached the server: the device is offline or the server is down. */
export class NetworkError extends Error {
  constructor(cause?: unknown) {
    super('No connection')
    this.cause = cause
  }
}

export function isNetworkError(error: unknown): error is NetworkError {
  return error instanceof NetworkError
}

function csrfToken(): string | undefined {
  return document.cookie
    .split('; ')
    .find((c) => c.startsWith('csrftoken='))
    ?.split('=')[1]
}

type RequestOptions = { method?: string; body?: unknown; signal?: AbortSignal }

/**
 * Calls the API on the same origin (Vite proxies /api to Django in development), so the
 * session cookie and CSRF token just work (ADR-24). Changes send the CSRF token header.
 */
export async function api<T>(path: string, { method = 'GET', body, signal }: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (method !== 'GET') {
    const token = csrfToken()
    if (token) headers['X-CSRFToken'] = token
  }
  let response: Response
  try {
    response = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: 'same-origin',
      signal,
    })
  } catch (error) {
    if (signal?.aborted) throw error
    throw new NetworkError(error)
  }
  if (response.status === 204) return undefined as T
  // A proxy or service worker answering for an unreachable server counts as offline.
  if (response.status === 502 || response.status === 503 || response.status === 504) {
    const isJson = response.headers.get('content-type')?.includes('application/json')
    if (!isJson) throw new NetworkError(response.status)
  }
  const data = (await response.json().catch(() => ({}))) as Record<string, unknown>
  if (!response.ok) throw new ApiError(response.status, data)
  return data as T
}

export async function getHealth(signal?: AbortSignal): Promise<Health> {
  const response = await fetch('/api/health/', { signal, credentials: 'same-origin' })
  if (!response.ok && response.status !== 503) {
    throw new Error(`Health check failed with status ${response.status}`)
  }
  return (await response.json()) as Health
}

export const paths = {
  session: '/api/auth/session/',
  login: '/api/auth/login/',
  logout: '/api/auth/logout/',
  workspaces: '/api/workspaces/',
  schema: (ws: string) => `/api/workspaces/${ws}/schema/`,
  tables: (ws: string) => `/api/workspaces/${ws}/tables/`,
  records: (ws: string, table: string) => `/api/workspaces/${ws}/tables/${table}/records/`,
  record: (ws: string, table: string, id: string) => `/api/workspaces/${ws}/tables/${table}/records/${id}/`,
  lookup: (ws: string, table: string) => `/api/workspaces/${ws}/tables/${table}/lookup/`,
  sync: (ws: string) => `/api/workspaces/${ws}/sync/`,
}
