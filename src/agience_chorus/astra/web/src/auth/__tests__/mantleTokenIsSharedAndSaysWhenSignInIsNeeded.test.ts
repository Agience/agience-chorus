/**
 * The web app's token for Mantle comes from the person's Origin session
 * (`POST /auth/me/authority/mantle-token`).
 *
 * - A page load asks for it from many places at once. One request is made and shared by every
 *   caller, and its token is kept until shortly before it expires.
 * - With no Origin session, Origin answers 401. The app then says so (`ORIGIN_SESSION_REQUIRED`,
 *   which the "sign in again" notice listens for), rather than showing an empty workspace.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mantleTokenFor, ORIGIN_SESSION_REQUIRED, resetMantleTokenForTests } from '../mantleToken'

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  resetMantleTokenForTests()
})

function answering(status: number, body: unknown) {
  const calls: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    calls.push(url)
    await new Promise((r) => setTimeout(r, 5))
    return new Response(JSON.stringify(body), {
      status, headers: { 'content-type': 'application/json' } })
  }))
  return calls
}

describe('the token for Mantle', () => {
  it('is asked for once by many callers at the same time', async () => {
    const calls = answering(200, { access_token: 'for-mantle', expires_in: 600 })
    const got = await Promise.all(Array.from({ length: 8 }, () =>
      mantleTokenFor('PERSON', 'https://origin.test')))
    expect(got).toEqual(Array(8).fill('for-mantle'))
    expect(calls).toHaveLength(1)
    expect(await mantleTokenFor('PERSON', 'https://origin.test')).toBe('for-mantle')
    expect(calls).toHaveLength(1)
  })

  it('says sign-in is needed when Origin holds no session for this browser', async () => {
    answering(401, { detail: 'sign in at Origin' })
    const heard = vi.fn()
    window.addEventListener(ORIGIN_SESSION_REQUIRED, heard)
    try {
      await expect(Promise.all([mantleTokenFor('PERSON', 'https://origin.test'),
                                mantleTokenFor('PERSON', 'https://origin.test')])).rejects.toThrow()
      expect(heard).toHaveBeenCalledTimes(1)
    } finally {
      window.removeEventListener(ORIGIN_SESSION_REQUIRED, heard)
    }
  })

  it('asks again after a refusal, not from a kept failure', async () => {
    answering(401, {})
    await expect(mantleTokenFor('PERSON', 'https://origin.test')).rejects.toThrow()
    const calls = answering(200, { access_token: 'later', expires_in: 600 })
    expect(await mantleTokenFor('PERSON', 'https://origin.test')).toBe('later')
    expect(calls).toHaveLength(1)
  })
})

// Review of the local-check fixes: the browser's Origin session may be another person's (B signed
// in at Origin's page in another tab). The web app never calls Mantle as them.
function jwtFor(sub: string, aud = 'origin'): string {
  const b = (o: unknown) => btoa(JSON.stringify(o)).replace(/=+$/, '').replace(/\+/g, '-')
    .replace(/\//g, '_')
  return `${b({ alg: 'none' })}.${b({ sub, aud })}.x`
}

describe('the token for Mantle names the person signed in here', () => {
  it('tells Origin whom it expects', async () => {
    const bodies: unknown[] = []
    vi.stubGlobal('fetch', vi.fn(async (_u: string, init: RequestInit) => {
      bodies.push(JSON.parse(String(init.body)))
      return new Response(JSON.stringify({ access_token: jwtFor('alice', 'mantle'), expires_in: 600 }),
                          { status: 200 })
    }))
    expect(await mantleTokenFor(jwtFor('alice'), 'https://origin.test')).toBe(jwtFor('alice', 'mantle'))
    expect(bodies).toEqual([{ expect_sub: 'alice' }])
  })

  it('refuses a token for anyone else, says sign-in is needed, and keeps nothing', async () => {
    const heard = vi.fn()
    window.addEventListener(ORIGIN_SESSION_REQUIRED, heard)
    try {
      answering(200, { access_token: jwtFor('bob', 'mantle'), expires_in: 600 })
      await expect(mantleTokenFor(jwtFor('alice'), 'https://origin.test')).rejects.toThrow()
      expect(heard).toHaveBeenCalledTimes(1)
      answering(409, { detail: 'another person' })
      await expect(mantleTokenFor(jwtFor('alice'), 'https://origin.test')).rejects.toThrow()
      expect(heard).toHaveBeenCalledTimes(2)
      const calls = answering(200, { access_token: jwtFor('alice', 'mantle'), expires_in: 600 })
      expect(await mantleTokenFor(jwtFor('alice'), 'https://origin.test')).toBe(jwtFor('alice', 'mantle'))
      expect(calls).toHaveLength(1)
    } finally {
      window.removeEventListener(ORIGIN_SESSION_REQUIRED, heard)
    }
  })
})
