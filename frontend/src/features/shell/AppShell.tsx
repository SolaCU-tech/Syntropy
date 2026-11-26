import {
  Activity,
  FileText,
  Home,
  Inbox,
  LogOut,
  Menu,
  MessageCircleQuestion,
  Plus,
  Settings,
  Sparkles,
  Table2,
  ChartColumn,
  Upload,
  type LucideIcon,
} from 'lucide-react'
import { useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router'

import { Button } from '@/components/ui/button'
import { useAuth } from '@/features/auth/auth-context'
import { SyncPill } from '@/features/sync/SyncPill'
import { useWorkspace } from '@/features/workspace/context'
import { cn } from '@/lib/utils'

type NavItem = { to: string; label: string; icon: LucideIcon }

// ADR-16: Home, Tables, Forms, Ask, Reports, Suggestions, Imports, Activity, Settings.
const groups: { title?: string; items: NavItem[] }[] = [
  { items: [{ to: 'home', label: 'Home', icon: Home }] },
  {
    title: 'Your data',
    items: [
      { to: 'tables', label: 'Tables', icon: Table2 },
      { to: 'forms', label: 'Forms', icon: FileText },
    ],
  },
  {
    title: 'Understand',
    items: [
      { to: 'ask', label: 'Ask', icon: MessageCircleQuestion },
      { to: 'reports', label: 'Reports', icon: ChartColumn },
    ],
  },
  { title: 'Improve', items: [{ to: 'suggestions', label: 'Suggestions', icon: Sparkles }] },
]
const bottomItems: NavItem[] = [
  { to: 'imports', label: 'Imports', icon: Upload },
  { to: 'activity', label: 'Activity', icon: Activity },
  { to: 'settings', label: 'Settings', icon: Settings },
]

function SideLink({ item, base, onClick }: { item: NavItem; base: string; onClick?: () => void }) {
  return (
    <NavLink
      to={`${base}/${item.to}`}
      onClick={onClick}
      className={({ isActive }) =>
        cn(
          'flex h-9 items-center gap-3 rounded-md px-3 text-sm text-on-brand/80 transition-colors hover:bg-white/10 hover:text-on-brand',
          isActive && 'bg-white/12 font-medium text-on-brand shadow-[inset_2px_0_0_var(--syn-gold)]',
        )
      }
    >
      <item.icon className="size-4" aria-hidden="true" />
      {item.label}
    </NavLink>
  )
}

function Sidebar({ base, onNavigate }: { base: string; onNavigate?: () => void }) {
  const { workspace } = useWorkspace()
  return (
    <div className="flex h-full flex-col gap-4 bg-brand px-3 py-4 text-on-brand">
      <div className="px-3">
        <p className="text-lg font-semibold text-champagne-on-brand">Syntropy</p>
        <p className="truncate text-xs text-on-brand/70" title={workspace.name}>
          {workspace.name}
        </p>
      </div>
      <nav aria-label="Main" className="flex flex-1 flex-col gap-4 overflow-y-auto">
        {groups.map((group, i) => (
          <div key={i} className="flex flex-col gap-0.5">
            {group.title && (
              <p className="px-3 pb-1 text-[11px] font-medium tracking-wide text-on-brand/55 uppercase">{group.title}</p>
            )}
            {group.items.map((item) => (
              <SideLink key={item.to} item={item} base={base} onClick={onNavigate} />
            ))}
          </div>
        ))}
        <div className="mt-auto flex flex-col gap-0.5">
          {bottomItems.map((item) => (
            <SideLink key={item.to} item={item} base={base} onClick={onNavigate} />
          ))}
        </div>
      </nav>
    </div>
  )
}

export function AppShell() {
  const { workspace, ssd } = useWorkspace()
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)
  const base = `/w/${workspace.slug}`
  const firstTable = ssd?.tables[0]

  return (
    <div className="flex min-h-dvh">
      <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 md:block">
        <Sidebar base={base} />
      </aside>

      {menuOpen && (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true" aria-label="Menu">
          <button className="absolute inset-0 bg-ink/40" aria-label="Close menu" onClick={() => setMenuOpen(false)} />
          <div className="absolute inset-y-0 left-0 w-64">
            <Sidebar base={base} onNavigate={() => setMenuOpen(false)} />
          </div>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b bg-surface/95 px-4 backdrop-blur">
          <Button variant="ghost" size="icon" className="md:hidden" aria-label="Open menu" onClick={() => setMenuOpen(true)}>
            <Menu />
          </Button>
          <p className="truncate font-medium text-ink md:hidden">{workspace.name}</p>
          <div className="ml-auto flex items-center gap-2">
            <SyncPill workspaceId={workspace.id} slug={workspace.slug} />
            {firstTable && (
              <Button size="sm" className="hidden sm:inline-flex" onClick={() => navigate(`${base}/forms`)}>
                <Plus /> New
              </Button>
            )}
            <span className="hidden text-sm text-text-secondary lg:inline">{user?.first_name || user?.username}</span>
            <Button variant="ghost" size="icon" aria-label="Sign out" title="Sign out" onClick={() => void logout()}>
              <LogOut />
            </Button>
          </div>
        </header>

        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 pb-24 md:px-8 md:pb-10">
          <Outlet />
        </main>

        {/* Mobile: Home, Tables, a large +, Reports and More (spec section 15). */}
        <nav aria-label="Quick" className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t bg-surface md:hidden">
          <MobileTab to={`${base}/home`} icon={Home} label="Home" />
          <MobileTab to={`${base}/tables`} icon={Table2} label="Tables" />
          <NavLink
            to={`${base}/forms`}
            aria-label="New record"
            className="mx-auto -mt-5 flex size-14 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-md"
          >
            <Plus className="size-6" />
          </NavLink>
          <MobileTab to={`${base}/reports`} icon={ChartColumn} label="Reports" />
          <button className="flex flex-col items-center justify-center gap-0.5 py-2 text-xs text-text-secondary" onClick={() => setMenuOpen(true)}>
            <Inbox className="size-5" aria-hidden="true" />
            More
          </button>
        </nav>
      </div>
    </div>
  )
}

function MobileTab({ to, icon: Icon, label }: { to: string; icon: LucideIcon; label: string }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        cn('flex flex-col items-center justify-center gap-0.5 py-2 text-xs text-text-secondary', isActive && 'font-medium text-primary')
      }
    >
      <Icon className="size-5" aria-hidden="true" />
      {label}
    </NavLink>
  )
}
