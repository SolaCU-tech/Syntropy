import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'

function mockFetch(body: unknown, status = 200) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('App', () => {
  it('shows the backend as running when the health check passes', async () => {
    mockFetch({ status: 'ok', database: 'ok' })
    render(<App />)
    expect(await screen.findByText(/Backend and database are running/)).toBeInTheDocument()
  })

  it('explains what to do when the backend is unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    render(<App />)
    expect(await screen.findByText(/can't reach the backend/)).toBeInTheDocument()
  })

  it('reports a degraded backend instead of crashing', async () => {
    mockFetch({ status: 'degraded', database: 'unavailable' }, 503)
    render(<App />)
    expect(await screen.findByText(/can't reach the backend/)).toBeInTheDocument()
  })
})
