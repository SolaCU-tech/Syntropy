import { createContext, useContext } from 'react'

import type { Schemas } from '@/api/client'

type User = Schemas['User']

export type AuthValue = {
  user: User | null
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  /** Signs out and clears this device's cache and queue (spec section 13, security). */
  logout: (options?: { force?: boolean }) => Promise<'done' | 'unsynced'>
}

export const AuthContext = createContext<AuthValue | null>(null)

export function useAuth(): AuthValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth outside AuthProvider')
  return value
}
