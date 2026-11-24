import { describe, expect, it } from 'vitest'

import css from './tokens.css?raw'

/**
 * Locks the light-theme tokens to the spec (section 14) and checks WCAG contrast.
 * If a test here fails after a colour change, the spec's decision register needs updating too.
 */
const rootBlock = css.slice(css.indexOf(':root {'), css.indexOf('}', css.indexOf(':root {')))

function token(name: string): string {
  const match = rootBlock.match(new RegExp(`--syn-${name}:\\s*(#[0-9a-fA-F]{6})`))
  if (!match) throw new Error(`Token --syn-${name} not found`)
  return match[1].toLowerCase()
}

function luminance(hex: string): number {
  const channels = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
  const [r, g, b] = channels.map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

describe('design tokens', () => {
  it('match the spec values', () => {
    expect({
      primary: token('primary'),
      'primary-hover': token('primary-hover'),
      'primary-soft': token('primary-soft'),
      ai: token('ai'),
      'ai-soft': token('ai-soft'),
      ink: token('ink'),
      'text-secondary': token('text-secondary'),
      'text-muted': token('text-muted'),
      canvas: token('canvas'),
      surface: token('surface'),
      border: token('border'),
      success: token('success'),
      warning: token('warning'),
      danger: token('danger'),
    }).toEqual({
      primary: '#0e7c6b',
      'primary-hover': '#0a6658',
      'primary-soft': '#e6f4f1',
      ai: '#6d5bd0',
      'ai-soft': '#efecfb',
      ink: '#0f1b2d',
      'text-secondary': '#526077',
      'text-muted': '#8a94a6',
      canvas: '#f7f8fa',
      surface: '#ffffff',
      border: '#e3e7ed',
      success: '#1f9d55',
      warning: '#d99a0b',
      danger: '#d64545',
    })
  })

  it('keeps violet out of the chart palette', () => {
    const chart = [1, 2, 3, 4, 5, 6].map((n) => token(`chart-${n}`))
    expect(chart).toEqual(['#0e7c6b', '#2f6fdb', '#e0a100', '#e4572e', '#5b6b82', '#4c9a2a'])
    expect(chart).not.toContain(token('ai'))
  })

  it.each([
    ['ink on canvas', 'ink', 'canvas'],
    ['ink on surface', 'ink', 'surface'],
    ['secondary text on canvas', 'text-secondary', 'canvas'],
    ['secondary text on surface', 'text-secondary', 'surface'],
    ['white button text on primary', 'surface', 'primary'],
    ['white button text on primary hover', 'surface', 'primary-hover'],
    ['primary link on surface', 'primary', 'surface'],
    ['primary link on canvas', 'primary', 'canvas'],
    ['AI violet on surface', 'ai', 'surface'],
  ])('%s meets WCAG AA for body text (4.5:1)', (_label, fg, bg) => {
    expect(contrast(token(fg), token(bg))).toBeGreaterThanOrEqual(4.5)
  })
})
