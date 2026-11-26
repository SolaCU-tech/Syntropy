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
    const names = [
      'primary', 'primary-hover', 'primary-soft', 'brand', 'gold', 'gold-text', 'champagne',
      'champagne-on-brand', 'ai', 'ai-soft', 'ink', 'text-secondary', 'text-muted', 'canvas',
      'surface', 'border', 'success', 'success-text', 'warning', 'warning-text', 'danger',
    ]
    expect(Object.fromEntries(names.map((n) => [n, token(n)]))).toEqual({
      primary: '#1d3a6b',
      'primary-hover': '#142b52',
      'primary-soft': '#e9eef6',
      brand: '#0b1a33',
      gold: '#b8913a',
      'gold-text': '#86672a',
      champagne: '#f5eedc',
      'champagne-on-brand': '#e8d7a8',
      ai: '#0e7c6b',
      'ai-soft': '#e6f4f1',
      ink: '#0f1b2d',
      'text-secondary': '#526077',
      'text-muted': '#667186',
      canvas: '#f7f8fa',
      surface: '#ffffff',
      border: '#e3e7ed',
      success: '#1f9d55',
      'success-text': '#1a8146',
      warning: '#d99a0b',
      'warning-text': '#936807',
      danger: '#d23434',
    })
  })

  it('keeps AI teal out of the chart palette', () => {
    const chart = [1, 2, 3, 4, 5, 6].map((n) => token(`chart-${n}`))
    expect(chart).toEqual(['#1d3a6b', '#4a9be8', '#e0b04a', '#b23a48', '#7e57c2', '#8a96a8'])
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
    ['AI teal on surface', 'ai', 'surface'],
    ['AI teal on AI soft', 'ai', 'ai-soft'],
    ['navy on primary soft (Verified badge)', 'primary', 'primary-soft'],
    ['gold text on surface', 'gold-text', 'surface'],
    ['gold text on canvas', 'gold-text', 'canvas'],
    ['gold text on champagne', 'gold-text', 'champagne'],
    ['white text on brand navy', 'on-brand', 'brand'],
    ['champagne text on brand navy', 'champagne-on-brand', 'brand'],
    ['gold on brand navy', 'gold', 'brand'],
    ['muted text on surface', 'text-muted', 'surface'],
    ['muted text on canvas', 'text-muted', 'canvas'],
    ['success text on surface', 'success-text', 'surface'],
    ['success text on canvas', 'success-text', 'canvas'],
    ['warning text on surface', 'warning-text', 'surface'],
    ['warning text on canvas', 'warning-text', 'canvas'],
    ['danger text on surface', 'danger', 'surface'],
    ['danger text on canvas', 'danger', 'canvas'],
    ['white text on danger button', 'surface', 'danger'],
  ])('%s meets WCAG AA for body text (4.5:1)', (_label, fg, bg) => {
    expect(contrast(token(fg), token(bg))).toBeGreaterThanOrEqual(4.5)
  })
})
