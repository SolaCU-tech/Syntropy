import { BadgeCheck, ScanText, Sparkles, type LucideIcon } from 'lucide-react'
import { cva } from 'class-variance-authority'
import type * as React from 'react'

import { cn } from '@/lib/utils'

/**
 * Where a value came from (spec section 14, colour principle 7):
 *   - suggested: AI made it and nobody has accepted it yet
 *   - extracted: read from an uploaded file or image, not yet checked
 *   - verified: entered or confirmed by a person, or reconciled
 * The three differ by fill, border style, icon and word, so colour is never the only signal.
 */
export type Provenance = 'suggested' | 'extracted' | 'verified'

const labels: Record<Provenance, { word: string; icon: LucideIcon }> = {
  suggested: { word: 'Suggested', icon: Sparkles },
  extracted: { word: 'Extracted', icon: ScanText },
  verified: { word: 'Verified', icon: BadgeCheck },
}

const badgeVariants = cva(
  'inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium [&_svg]:size-3.5 [&_svg]:shrink-0',
  {
    variants: {
      provenance: {
        suggested: 'border-dashed border-suggested-border bg-suggested-bg text-suggested',
        extracted: 'border-solid border-extracted-border bg-extracted-bg text-extracted',
        verified: 'border-verified-border bg-verified-bg text-verified',
      },
    },
  },
)

/** Styles a value inside a table cell or form field according to its provenance. */
export const provenanceValue = cva('', {
  variants: {
    provenance: {
      suggested: 'rounded-sm bg-suggested-bg px-0.5 underline decoration-suggested decoration-dashed underline-offset-4',
      extracted: 'underline decoration-extracted decoration-dotted decoration-2 underline-offset-4',
      verified: 'text-ink',
    },
  },
})

function ProvenanceBadge({
  provenance,
  source,
  className,
  ...props
}: React.ComponentProps<'span'> & { provenance: Provenance; source?: string }) {
  const { word, icon: Icon } = labels[provenance]
  return (
    <span
      data-provenance={provenance}
      title={source ? `${word} from ${source}` : undefined}
      className={cn(badgeVariants({ provenance }), className)}
      {...props}
    >
      <Icon aria-hidden="true" />
      {word}
    </span>
  )
}

export { ProvenanceBadge }
