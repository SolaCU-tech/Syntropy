import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ProvenanceBadge, provenanceValue } from './provenance'

describe('ProvenanceBadge', () => {
  it.each([
    ['suggested', 'Suggested'],
    ['extracted', 'Extracted'],
    ['verified', 'Verified'],
  ] as const)('labels %s values with a word, not just a colour', (provenance, word) => {
    render(<ProvenanceBadge provenance={provenance} />)
    expect(screen.getByText(word)).toHaveAttribute('data-provenance', provenance)
  })

  it('names the source of an extracted value', () => {
    render(<ProvenanceBadge provenance="extracted" source="sales-may.xlsx" />)
    expect(screen.getByText('Extracted')).toHaveAttribute('title', 'Extracted from sales-may.xlsx')
  })

  it('gives the three states different styles', () => {
    const badges = (['suggested', 'extracted', 'verified'] as const).map((p) => {
      const { container } = render(<ProvenanceBadge provenance={p} />)
      return container.firstElementChild?.className
    })
    expect(new Set(badges).size).toBe(3)
    const values = (['suggested', 'extracted', 'verified'] as const).map((p) => provenanceValue({ provenance: p }))
    expect(new Set(values).size).toBe(3)
  })
})
