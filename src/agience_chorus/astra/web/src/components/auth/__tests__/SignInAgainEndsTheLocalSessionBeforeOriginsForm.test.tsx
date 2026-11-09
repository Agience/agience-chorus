/**
 * 2026-11-09, production: Origin still accepted the stored token at `/auth/userinfo` but refused
 * `narrow` and `mantle-token` with 401 (the person's Origin session had ended). "Sign in again"
 * went to Origin's `/login` with that token still stored on both sides: Origin's page handed its
 * own stale token straight back (silent SSO), the app reloaded with it, and the same notice came
 * back. The person never reached a sign-in form.
 *
 * Signing in again ends the local session first (the stored token and the cached token for
 * Mantle), and asks Origin for a fresh sign-in (`prompt=login`), so its form is shown.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'

const runtime = vi.hoisted(() => ({ idpUri: '' }))
vi.mock('../../../config/runtime', () => ({
  getRuntimeConfig: () => ({ originUri: 'https://origin.example', clientId: 'platform', ...runtime }),
}))
vi.mock('../../../api/api', () => ({ get: vi.fn(), del: vi.fn() }))

import { get } from '../../../api/api'
import { AuthProvider } from '../../../context/auth/AuthProvider'
import { ORIGIN_SESSION_REQUIRED } from '../../../auth/mantleToken'
import OriginSessionNotice from '../OriginSessionNotice'

const getMock = get as unknown as ReturnType<typeof vi.fn>

let navigated: string[]

function stubLocation(origin: string) {
  navigated = []
  vi.stubGlobal('location', {
    origin, hash: '', pathname: '/', search: '',
    get href() { return `${origin}/` },
    set href(v: string) { navigated.push(v) },
    assign: (v: string) => { navigated.push(v) },
    replace: (v: string) => { navigated.push(v) },
  } as unknown as Location)
}

async function showNoticeAndClick() {
  render(<AuthProvider><OriginSessionNotice /></AuthProvider>)
  await waitFor(() => expect(getMock).toHaveBeenCalledWith('/auth/userinfo', expect.anything()))
  act(() => { window.dispatchEvent(new CustomEvent(ORIGIN_SESSION_REQUIRED)) })
  fireEvent.click(screen.getByRole('button', { name: /sign in again/i }))
}

async function reloadFindsNoOldSession() {
  getMock.mockClear()
  render(<AuthProvider><OriginSessionNotice /></AuthProvider>)
  await act(async () => { await Promise.resolve() })
  expect(getMock).not.toHaveBeenCalled()
  expect(screen.queryByRole('alertdialog')).toBeNull()
}

describe('signing in again after Origin ended the session', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    getMock.mockReset()
    getMock.mockResolvedValue({ id: 'u1', email: 'a@example.com', name: 'A' })
    localStorage.setItem('access_token', 'stale.jwt')
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    runtime.idpUri = ''
  })

  it('on a service provider, clears the stored token and asks Origin for its form', async () => {
    runtime.idpUri = 'https://origin.example'
    stubLocation('https://app.example')
    await showNoticeAndClick()

    expect(localStorage.getItem('access_token')).toBeNull()
    await waitFor(() => expect(navigated.length).toBe(1))
    const to = new URL(navigated[0])
    expect(`${to.origin}${to.pathname}`).toBe('https://origin.example/login')
    expect(to.searchParams.get('prompt')).toBe('login')
    expect(to.searchParams.get('redirect_uri')).toBe('https://app.example/')
    expect(to.searchParams.get('state')).toBeTruthy()

    await reloadFindsNoOldSession()
  })

  it('on Origin\'s own deployment, clears the stored token and goes to the authorize form', async () => {
    stubLocation('https://origin.example')
    await showNoticeAndClick()

    expect(localStorage.getItem('access_token')).toBeNull()
    await waitFor(() => expect(navigated.length).toBe(1))
    const to = new URL(navigated[0])
    expect(`${to.origin}${to.pathname}`).toBe('https://origin.example/auth/authorize')
    expect(to.searchParams.get('provider')).toBe('local')

    await reloadFindsNoOldSession()
  })
})
