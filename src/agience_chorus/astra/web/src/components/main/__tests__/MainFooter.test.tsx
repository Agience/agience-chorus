import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { FooterLabel } from '../MainFooter'

describe('the footer', () => {
  it('a release build shows exactly that release and commit, each linked to GitHub', () => {
    const { container } = render(<FooterLabel release="2026.11.4" sha="6da03e5" />)
    expect(container.textContent).toBe('2026.11.4 · 6da03e5')
    expect(screen.getByText('2026.11.4').getAttribute('href'))
      .toBe('https://github.com/Agience/agience-chorus/releases/tag/platform/2026.11.4')
    expect(screen.getByText('6da03e5').getAttribute('href'))
      .toBe('https://github.com/Agience/agience-chorus/commit/6da03e5')
  })

  it('a build that is not a release shows dev and its commit', () => {
    const { container } = render(<FooterLabel release="" sha="abc1234" />)
    expect(container.textContent).toBe('dev · abc1234')
    expect(screen.queryByRole('link', { name: /dev/ })).toBeNull()
  })
})
