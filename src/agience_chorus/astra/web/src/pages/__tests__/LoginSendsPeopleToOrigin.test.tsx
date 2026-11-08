/**
 * The web app's sign-in page sends people to Origin's own page to sign in (its `/auth/authorize`
 * form: password, a mailed code, a new account, or a provider). Credentials are typed only there,
 * and a sign-in there starts the person's Origin session, which the web app's token for Mantle
 * and every sharing change are made in. The web app never posts a password or a code itself.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import Login from '../Login'

const login = vi.fn()
const post = vi.fn()
vi.mock('../../hooks/useAuth', () => ({
  useAuth: () => ({ login, setAuthData: vi.fn(), isAuthenticated: false }),
}))
vi.mock('../../api/api', () => ({
  get: vi.fn(async () => ({ providers: [{ name: 'google', label: 'Google', type: 'oidc' }],
                            password: true, otp: true })),
  post: (...a: unknown[]) => post(...a),
}))
vi.mock('../../components/layout/AuthLayout', () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))

function renderLogin(path = '/login') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/login" element={<Login />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('the web app sign-in page', () => {
  beforeEach(() => {
    login.mockReset()
    post.mockReset()
  })
  afterEach(() => sessionStorage.clear())

  it('offers no password or code form of its own', async () => {
    renderLogin()
    await screen.findByRole('button', { name: /continue to sign in/i })
    expect(document.querySelector('input[type=password]')).toBeNull()
    expect(document.querySelector('#identifier')).toBeNull()
  })

  it('sends the person to Origin\'s sign-in page', async () => {
    renderLogin()
    fireEvent.click(await screen.findByRole('button', { name: /continue to sign in/i }))
    await waitFor(() => expect(login).toHaveBeenCalledWith('local', undefined))
    expect(post).not.toHaveBeenCalled()
  })

  it('keeps a provider button going to Origin for that provider', async () => {
    renderLogin()
    fireEvent.click(await screen.findByRole('button', { name: /google/i }))
    await waitFor(() => expect(login).toHaveBeenCalledWith('google', undefined))
  })
})
