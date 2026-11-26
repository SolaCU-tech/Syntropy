import { Clock } from 'lucide-react'

import { EmptyState, PageHeader } from '@/components/ui/field'

/** A destination from ADR-16 whose screens arrive in a later roadmap phase. */
export function ComingLater({ title, phase, what }: { title: string; phase: number; what: string }) {
  return (
    <>
      <PageHeader title={title} />
      <EmptyState icon={<Clock />} title={`Coming in phase ${phase}`}>
        {what}
      </EmptyState>
    </>
  )
}
