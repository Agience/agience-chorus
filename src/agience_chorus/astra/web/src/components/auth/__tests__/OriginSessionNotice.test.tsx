/**
 * When Origin holds no session for this browser, the web app cannot get its token for Mantle, and
 * every workspace read fails. The person is told, with a way to sign in again at Origin, rather
 * than shown an empty app. Where signing in again goes, and what it clears first, is the
 * AuthProvider's (`SignInAgainEndsTheLocalSessionBeforeOriginsForm.test.tsx`).
 */
import { describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'

import { ORIGIN_SESSION_REQUIRED } from '../../../auth/mantleToken'
import OriginSessionNotice from '../OriginSessionNotice'

const signInAgain = vi.fn()
vi.mock('../../../hooks/useAuth', () => ({
  useAuth: () => ({ signInAgain, isAuthenticated: true }),
}))

describe('the sign-in-again notice', () => {
  it('shows nothing until Origin says it holds no session', () => {
    render(<OriginSessionNotice />)
    expect(screen.queryByRole('alertdialog')).toBeNull()
  })

  it('asks the person to sign in again', () => {
    render(<OriginSessionNotice />)
    act(() => { window.dispatchEvent(new CustomEvent(ORIGIN_SESSION_REQUIRED)) })
    expect(screen.getByRole('alertdialog')).toHaveTextContent(/sign in again/i)
    fireEvent.click(screen.getByRole('button', { name: /sign in again/i }))
    expect(signInAgain).toHaveBeenCalledTimes(1)
  })
})
