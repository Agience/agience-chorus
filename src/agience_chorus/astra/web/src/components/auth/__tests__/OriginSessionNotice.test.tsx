/**
 * When Origin holds no session for this browser, the web app cannot get its token for Mantle, and
 * every workspace read fails. The person is told, with a way to sign in again at Origin, rather
 * than shown an empty app.
 */
import { describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'

import { ORIGIN_SESSION_REQUIRED } from '../../../auth/mantleToken'
import OriginSessionNotice from '../OriginSessionNotice'

const login = vi.fn()
vi.mock('../../../hooks/useAuth', () => ({
  useAuth: () => ({ login, isAuthenticated: true }),
}))

describe('the sign-in-again notice', () => {
  it('shows nothing until Origin says it holds no session', () => {
    render(<OriginSessionNotice />)
    expect(screen.queryByRole('alertdialog')).toBeNull()
  })

  it('asks the person to sign in again, at Origin', () => {
    render(<OriginSessionNotice />)
    act(() => { window.dispatchEvent(new CustomEvent(ORIGIN_SESSION_REQUIRED)) })
    expect(screen.getByRole('alertdialog')).toHaveTextContent(/sign in again/i)
    fireEvent.click(screen.getByRole('button', { name: /sign in again/i }))
    expect(login).toHaveBeenCalledWith('local')
  })
})

// As a service provider (production: `idpUri` names Origin, another host), the web app has no
// sign-in of its own and its host serves no `/auth/*`: signing in again goes to the IdP's page.
describe('the sign-in-again notice on a service-provider deployment', () => {
  it('sends the person to the IdP\'s sign-in page', () => {
    (window as { __AGIENCE_CONFIG__?: unknown }).__AGIENCE_CONFIG__ = { idpUri: 'https://origin.example' }
    const assign = vi.fn()
    vi.stubGlobal('location', { ...window.location, origin: 'https://app.example', href: 'https://app.example/', assign })
    try {
      login.mockReset()
      render(<OriginSessionNotice />)
      act(() => { window.dispatchEvent(new CustomEvent(ORIGIN_SESSION_REQUIRED)) })
      fireEvent.click(screen.getAllByRole('button', { name: /sign in again/i }).pop()!)
      expect(login).not.toHaveBeenCalled()
      const to = new URL(assign.mock.calls[0][0])
      expect(`${to.origin}${to.pathname}`).toBe('https://origin.example/login')
      expect(to.searchParams.get('redirect_uri')).toBe('https://app.example/')
    } finally {
      delete (window as { __AGIENCE_CONFIG__?: unknown }).__AGIENCE_CONFIG__
      vi.unstubAllGlobals()
    }
  })
})
