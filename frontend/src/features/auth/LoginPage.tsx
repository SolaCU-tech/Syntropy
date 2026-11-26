import { Loader2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Navigate } from 'react-router'

import { ApiError, isNetworkError } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Input, Label } from '@/components/ui/field'

import { useAuth } from './auth-context'

export function LoginPage() {
  const { user, login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (user) return <Navigate to="/" replace />

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(username, password)
    } catch (err) {
      if (isNetworkError(err)) setError('You are offline. Signing in needs a connection.')
      else if (err instanceof ApiError) setError(err.message)
      else setError('Something went wrong. Try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-dvh items-center justify-center bg-brand px-4">
      <div className="w-full max-w-sm rounded-xl bg-surface p-8 shadow-md">
        <p className="text-2xl font-semibold text-ink">Syntropy</p>
        <span className="mt-2 block h-0.5 w-10 rounded-full bg-gold" aria-hidden="true" />
        <p className="mt-4 mb-6 text-text-secondary">Sign in to your business workspace.</p>
        <form onSubmit={submit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="username">Username</Label>
            <Input id="username" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          {error && (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          )}
          <Button type="submit" size="lg" disabled={busy}>
            {busy && <Loader2 className="animate-spin" />} Sign in
          </Button>
        </form>
      </div>
    </div>
  )
}
