import { useEffect, useState } from 'react'
import { CheckCircle2, CircleAlert, Loader2 } from 'lucide-react'

import { getHealth, type Health } from '@/api/client'
import { Button } from '@/components/ui/button'
import { ProvenanceBadge, provenanceValue } from '@/components/ui/provenance'

type ApiState = { kind: 'loading' } | { kind: 'ready'; health: Health } | { kind: 'offline' }

const swatches = [
  { name: 'Brand navy', className: 'bg-brand' },
  { name: 'Primary', className: 'bg-primary' },
  { name: 'Primary soft', className: 'bg-secondary' },
  { name: 'Gold', className: 'bg-gold' },
  { name: 'Champagne', className: 'bg-champagne' },
  { name: 'AI teal', className: 'bg-ai' },
  { name: 'Success', className: 'bg-success' },
  { name: 'Warning', className: 'bg-warning' },
  { name: 'Danger', className: 'bg-danger' },
]

const chartColours = ['bg-chart-1', 'bg-chart-2', 'bg-chart-3', 'bg-chart-4', 'bg-chart-5', 'bg-chart-6']

function App() {
  const [api, setApi] = useState<ApiState>({ kind: 'loading' })

  useEffect(() => {
    const controller = new AbortController()
    getHealth(controller.signal)
      .then((health) => setApi({ kind: 'ready', health }))
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          console.warn(error)
          setApi({ kind: 'offline' })
        }
      })
    return () => controller.abort()
  }, [])

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-8 px-4 py-12">
      <header className="flex flex-col gap-2 rounded-xl bg-brand p-6 text-on-brand">
        <h1 className="text-3xl font-semibold text-champagne-on-brand">Syntropy</h1>
        <span className="h-0.5 w-12 rounded-full bg-gold" aria-hidden="true" />
        <p className="text-base">Turn scattered business records into order. This is the foundation screen.</p>
      </header>

      <section aria-labelledby="status-heading" className="rounded-lg border bg-surface p-6 shadow-sm">
        <h2 id="status-heading" className="mb-3 text-xl font-semibold">
          Connection
        </h2>
        <ApiStatus state={api} />
      </section>

      <section aria-labelledby="tokens-heading" className="rounded-lg border bg-surface p-6 shadow-sm">
        <h2 id="tokens-heading" className="mb-4 text-xl font-semibold">
          Design tokens
        </h2>
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {swatches.map((swatch) => (
            <li key={swatch.name} className="flex items-center gap-3">
              <span className={`size-8 rounded-md border ${swatch.className}`} aria-hidden="true" />
              <span>{swatch.name}</span>
            </li>
          ))}
        </ul>
        <p className="mt-6 mb-2 text-text-secondary">Chart palette</p>
        <div className="flex gap-2" aria-hidden="true">
          {chartColours.map((colour) => (
            <span key={colour} className={`h-6 flex-1 rounded-sm ${colour}`} />
          ))}
        </div>
        <div className="mt-6 flex flex-wrap items-center gap-3">
          <Button>Build my workspace</Button>
          <Button variant="outline">Add records</Button>
          <span className="tabular font-medium">₦1,200,000.00</span>
        </div>
        <p className="mt-6 mb-2 text-text-secondary">Where values came from</p>
        <ul className="flex flex-col gap-2">
          <li className="flex items-center gap-3">
            <ProvenanceBadge provenance="suggested" />
            <span>
              Category: <span className={provenanceValue({ provenance: 'suggested' })}>Beverages</span>
            </span>
          </li>
          <li className="flex items-center gap-3">
            <ProvenanceBadge provenance="extracted" source="sales-may.xlsx" />
            <span>
              Amount: <span className={`tabular ${provenanceValue({ provenance: 'extracted' })}`}>₦45,500.00</span>
            </span>
          </li>
          <li className="flex items-center gap-3">
            <ProvenanceBadge provenance="verified" />
            <span>
              Customer: <span className={provenanceValue({ provenance: 'verified' })}>Adaeze Okafor</span>
            </span>
          </li>
        </ul>
      </section>
    </main>
  )
}

function ApiStatus({ state }: { state: ApiState }) {
  if (state.kind === 'loading') {
    return (
      <p className="flex items-center gap-2 text-text-secondary">
        <Loader2 className="size-4 animate-spin" aria-hidden="true" /> Checking the backend…
      </p>
    )
  }
  if (state.kind === 'ready' && state.health.status === 'ok') {
    return (
      <p className="flex items-center gap-2">
        <CheckCircle2 className="size-4 text-success" aria-hidden="true" /> Backend and database are
        running.
      </p>
    )
  }
  return (
    <p className="flex items-center gap-2">
      <CircleAlert className="size-4 text-danger" aria-hidden="true" />
      We can't reach the backend yet. Start it with <code className="font-mono">python manage.py runserver</code>.
    </p>
  )
}

export default App
