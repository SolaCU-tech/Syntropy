import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { lazy, Suspense, type ReactNode } from 'react'
import { createBrowserRouter, Navigate, Outlet, RouterProvider, type RouteObject } from 'react-router'

import { isNetworkError } from '@/api/client'
import { useWorkspaces } from '@/api/hooks'
import { EmptyState } from '@/components/ui/field'
import { ToastProvider } from '@/components/toast'
import { useAuth } from '@/features/auth/auth-context'
import { AuthProvider } from '@/features/auth/AuthProvider'
import { LoginPage } from '@/features/auth/LoginPage'
import { Home } from '@/features/home/Home'
import { ComingLater } from '@/features/shell/ComingLater'
import { NotCachedError } from '@/features/sync/cache'
import { useWorkspace } from '@/features/workspace/context'
import { FullPageSpinner, WorkspaceLayout } from '@/features/workspace/WorkspaceLayout'

// Route-level code splitting keeps the first load light on low-end phones (spec section 12).
const TablesIndex = lazy(() => import('@/features/tables/TablesIndex').then((m) => ({ default: m.TablesIndex })))
const TableView = lazy(() => import('@/features/tables/TableView').then((m) => ({ default: m.TableView })))
const RecordPage = lazy(() => import('@/features/records/RecordPage').then((m) => ({ default: m.RecordPage })))
const FormsIndex = lazy(() => import('@/features/forms/pages').then((m) => ({ default: m.FormsIndex })))
const NewRecordPage = lazy(() => import('@/features/forms/pages').then((m) => ({ default: m.NewRecordPage })))
const EditRecordPage = lazy(() => import('@/features/forms/pages').then((m) => ({ default: m.EditRecordPage })))
const WaitingToSync = lazy(() => import('@/features/sync/WaitingToSync').then((m) => ({ default: m.WaitingToSync })))

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  if (loading) return <FullPageSpinner />
  if (!user) return <Navigate to="/login" replace />
  return children
}

/** Screens that need a published structure. */
function RequireSchema() {
  const { ssd } = useWorkspace()
  if (!ssd) {
    return (
      <EmptyState title="No structure yet">
        This workspace has no tables yet. Setting one up from your records arrives in the next phase.
      </EmptyState>
    )
  }
  return (
    <Suspense fallback={null}>
      <Outlet />
    </Suspense>
  )
}

function FirstWorkspace() {
  const { user } = useAuth()
  const workspaces = useWorkspaces(user?.id)
  if (workspaces.isPending) return <FullPageSpinner />
  const first = workspaces.data?.[0]
  if (first) return <Navigate to={`/w/${first.slug}/home`} replace />
  return (
    <div className="p-8">
      <EmptyState title={workspaces.error instanceof NotCachedError ? 'Needs a connection' : 'No workspace yet'}>
        {workspaces.error instanceof NotCachedError
          ? 'Open Syntropy once while online so it works offline next time.'
          : 'Creating your workspace from your records arrives in the next phase.'}
      </EmptyState>
    </div>
  )
}

const later = (title: string, phase: number, what: string) => <ComingLater title={title} phase={phase} what={what} />

const routes: RouteObject[] = [
  { path: '/login', element: <LoginPage /> },
  {
    path: '/',
    element: (
      <RequireAuth>
        <Outlet />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <FirstWorkspace /> },
      {
        path: 'w/:slug',
        element: <WorkspaceLayout />,
        children: [
          { index: true, element: <Navigate to="home" replace /> },
          { path: 'home', element: <Home /> },
          {
            element: <RequireSchema />,
            children: [
              { path: 'tables', element: <TablesIndex /> },
              { path: 'tables/:tableKey', element: <TableView /> },
              { path: 'tables/:tableKey/new', element: <NewRecordPage /> },
              { path: 'tables/:tableKey/:recordId', element: <RecordPage /> },
              { path: 'tables/:tableKey/:recordId/edit', element: <EditRecordPage /> },
              { path: 'forms', element: <FormsIndex /> },
              { path: 'forms/:tableKey', element: <NewRecordPage /> },
              { path: 'sync', element: <WaitingToSync /> },
            ],
          },
          { path: 'ask', element: later('Ask', 5, 'Ask questions about your business in plain words, such as "who owes me the most?".') },
          { path: 'reports', element: later('Reports', 5, 'Starter reports such as sales summary, top products and who owes you.') },
          { path: 'suggestions', element: later('Suggestions', 6, 'Improvements to your structure suggested by Syntropy, for you to approve.') },
          { path: 'imports', element: later('Imports', 4, 'Upload spreadsheets and let Syntropy organise them into tables.') },
          { path: 'activity', element: later('Activity', 5, 'A timeline of imports, edits, approvals and sync conflicts.') },
          { path: 'settings/*', element: later('Settings', 5, 'Workspace details, business profile, members and roles.') },
        ],
      },
      { path: '*', element: <Navigate to="/" replace /> },
    ],
  },
]

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Offline reads fall back to the device cache; retrying a dead connection only delays that.
        retry: (count, error: unknown) => !isNetworkError(error) && !(error instanceof NotCachedError) && count < 2,
        refetchOnWindowFocus: false,
        networkMode: 'always',
      },
      mutations: { networkMode: 'always' },
    },
  })
}

const queryClient = makeQueryClient()
const router = createBrowserRouter(routes)

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <AuthProvider>
          <RouterProvider router={router} />
        </AuthProvider>
      </ToastProvider>
    </QueryClientProvider>
  )
}
