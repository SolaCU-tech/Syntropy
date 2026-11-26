import type * as React from 'react'

import { cn } from '@/lib/utils'

const control =
  'h-11 w-full rounded-md border bg-surface px-3 text-sm text-ink shadow-sm outline-none transition-colors placeholder:text-text-muted focus-visible:border-primary focus-visible:ring-[3px] focus-visible:ring-ring/30 aria-invalid:border-danger disabled:opacity-60 sm:h-9'

export function Input({ className, ...props }: React.ComponentProps<'input'>) {
  return <input className={cn(control, className)} {...props} />
}

export function Select({ className, ...props }: React.ComponentProps<'select'>) {
  return <select className={cn(control, 'pr-8', className)} {...props} />
}

export function Textarea({ className, ...props }: React.ComponentProps<'textarea'>) {
  return <textarea className={cn(control, 'h-auto min-h-20 py-2', className)} {...props} />
}

export function Label({ className, ...props }: React.ComponentProps<'label'>) {
  return <label className={cn('text-sm font-medium text-ink', className)} {...props} />
}

export function Card({ className, ...props }: React.ComponentProps<'div'>) {
  return <div className={cn('rounded-lg border bg-surface shadow-sm', className)} {...props} />
}

type Tone = 'neutral' | 'primary' | 'success' | 'warning' | 'danger' | 'gold'
const tones: Record<Tone, string> = {
  neutral: 'bg-canvas text-text-secondary border-border',
  primary: 'bg-secondary text-primary border-transparent',
  success: 'bg-success/10 text-success-text border-transparent',
  warning: 'bg-warning/15 text-warning-text border-transparent',
  danger: 'bg-danger/10 text-danger border-transparent',
  gold: 'bg-champagne text-gold-text border-transparent',
}

export function Badge({ tone = 'neutral', className, ...props }: React.ComponentProps<'span'> & { tone?: Tone }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium whitespace-nowrap [&_svg]:size-3.5',
        tones[tone],
        className,
      )}
      {...props}
    />
  )
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: React.ReactNode
  description?: React.ReactNode
  actions?: React.ReactNode
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">{title}</h1>
        {description && <p className="mt-1 text-text-secondary">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function EmptyState({ icon, title, children }: { icon?: React.ReactNode; title: string; children?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed bg-surface px-6 py-12 text-center">
      {icon && <div className="text-text-muted [&_svg]:size-8">{icon}</div>}
      <p className="text-base font-medium text-ink">{title}</p>
      {children && <div className="max-w-md text-text-secondary">{children}</div>}
    </div>
  )
}
