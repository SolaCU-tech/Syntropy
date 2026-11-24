import type { components } from './types'

export type Health = components['schemas']['Health']

/**
 * Minimal API helper. Requests go to the same origin (Vite proxies /api to Django in
 * development), so the session cookie and CSRF token just work (ADR-24).
 */
export async function getHealth(signal?: AbortSignal): Promise<Health> {
  const response = await fetch('/api/health/', { signal, credentials: 'same-origin' })
  if (!response.ok && response.status !== 503) {
    throw new Error(`Health check failed with status ${response.status}`)
  }
  return (await response.json()) as Health
}
