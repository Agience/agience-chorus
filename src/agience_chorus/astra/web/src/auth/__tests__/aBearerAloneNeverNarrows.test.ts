/**
 * Review 23, H1: the web app gets every narrowed token, and its token for Mantle, in the person's
 * Origin session, never by handing a bearer to Origin's token endpoint.
 *
 * Mantle held the person's own token on every call, and Origin narrowed any bearer it was shown, so
 * Mantle could mint a delegation narrowed to any persona. Now the web app calls Origin's session
 * routes with the session cookie (`credentials: 'include'`) and `X-Origin-Session`:
 * `/auth/me/authority/narrow` for a persona, Crystal or a service provider, and
 * `/auth/me/authority/mantle-token` for the token it calls Mantle on. The person's own token is
 * never in the request.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mantleTokenFor, resetMantleTokenForTests } from '../mantleToken'
import { narrowedFor, resetNarrowedForTests } from '../narrowed'
import { tokenForSp } from '../spRedirect'

type Seen = { url: string; init: RequestInit }

function origin(seen: Seen[]) {
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit) => {
    seen.push({ url, init })
    const body = url.endsWith('/mantle-token') ? { access_token: 'for-mantle', expires_in: 600 }
      : { access_token: `for-${JSON.parse(String(init.body)).audience}`, expires_in: 300 }
    return new Response(JSON.stringify(body), {
      status: 200, headers: { 'content-type': 'application/json' } })
  }))
}

function inSession(s: Seen) {
  expect(s.init.method).toBe('POST')
  expect(s.init.credentials).toBe('include')
  expect((s.init.headers as Record<string, string>)['X-Origin-Session']).toBe('1')
  expect(String(s.init.body ?? '')).not.toContain('FULL')
  expect(JSON.stringify(s.init.headers)).not.toContain('FULL')
}

afterEach(() => {
  vi.restoreAllMocks()
  resetNarrowedForTests()
  resetMantleTokenForTests()
})

describe('a bearer alone never narrows', () => {
  it('narrows for a persona in the session', async () => {
    const seen: Seen[] = []
    origin(seen)
    expect(await narrowedFor('FULL', 'iris', 'https://origin.test')).toBe('for-iris')
    expect(seen[0].url).toBe('https://origin.test/auth/me/authority/narrow')
    inSession(seen[0])
  })

  it('narrows for a service provider in the session', async () => {
    const seen: Seen[] = []
    origin(seen)
    expect(await tokenForSp('FULL', 'https://aria.home.agience.ai/x', 'https://origin.test'))
      .toBe('for-https://aria.home.agience.ai')
    expect(seen[0].url).toBe('https://origin.test/auth/me/authority/narrow')
    inSession(seen[0])
  })

  it('gets the token it calls Mantle on in the session, once while it lives', async () => {
    const seen: Seen[] = []
    origin(seen)
    expect(await mantleTokenFor('FULL', 'https://origin.test')).toBe('for-mantle')
    expect(await mantleTokenFor('FULL', 'https://origin.test')).toBe('for-mantle')
    expect(seen.length).toBe(1)
    expect(seen[0].url).toBe('https://origin.test/auth/me/authority/mantle-token')
    inSession(seen[0])
  })

  it('never falls back to the person token for Mantle', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 401 })))
    await expect(mantleTokenFor('FULL', 'https://origin.test')).rejects.toThrow()
  })
})
