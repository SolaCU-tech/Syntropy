import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useMemo, type ReactNode } from 'react'

import { api, paths, type Session } from '@/api/client'
import { keys, useSession } from '@/api/hooks'
import { db, deleteUserDB, hasDB, openUserDB } from '@/features/sync/db'

import { AuthContext } from './auth-context'

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const session = useSession()
  const user = session.data?.authenticated ? (session.data.user ?? null) : null
  if (user) openUserDB(user.id)

  const login = useCallback(
    async (username: string, password: string) => {
      await api(paths.session) // sets the CSRF cookie
      const next = await api<Session>(paths.login, { method: 'POST', body: { username, password } })
      localStorage.setItem('syntropy-session', JSON.stringify(next))
      queryClient.setQueryData(keys.session, next)
    },
    [queryClient],
  )

  const logout = useCallback(
    async ({ force = false } = {}) => {
      if (!force && hasDB() && (await db().queue.count()) > 0) {
        const ok = window.confirm(
          'Some changes on this phone have not synced yet. Signing out deletes them. Sign out anyway?',
        )
        if (!ok) return 'unsynced' as const
      }
      await api(paths.logout, { method: 'POST' }).catch(() => undefined)
      await deleteUserDB()
      localStorage.removeItem('syntropy-session')
      queryClient.clear()
      queryClient.setQueryData(keys.session, { authenticated: false, user: null })
      return 'done' as const
    },
    [queryClient],
  )

  const value = useMemo(() => ({ user, loading: session.isPending, login, logout }), [user, session.isPending, login, logout])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
