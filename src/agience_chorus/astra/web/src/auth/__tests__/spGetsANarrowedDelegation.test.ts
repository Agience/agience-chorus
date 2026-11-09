/**
 * Review 8, R3: a service provider other than the platform's own web app never receives the
 * person's full platform token. Every persona page gets a delegation Origin narrows to it (RFC 8693 token exchange at `/auth/token`, `audience` the SP's), and if
 * Origin will not issue one, the SP gets nothing.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

import { KNOWN_SP_ORIGINS, spAudience, tokenForSp } from '../spRedirect'

afterEach(() => vi.restoreAllMocks())

describe('the token a service provider receives', () => {
  it('names an audience for every SP but the platform app and Origin', () => {
    expect(spAudience('https://aria.home.agience.ai/x')).toBe('https://aria.home.agience.ai')
    expect(spAudience('https://my.agience.ai/app')).toBeNull()
    expect(spAudience('https://origin.agience.ai/x')).toBeNull()
  })

  it('treats the retired Lumen site as no SP of the platform, and not as Ember', () => {
    expect(KNOWN_SP_ORIGINS).not.toContain('https://lumen.agience.ai')
    expect(spAudience('https://lumen.agience.ai/chat')).not.toBe('ember')
  })

  it("narrows to the SP in the person's Origin session, never by the full token", async () => {
    const seen: { url: string; body: string; init: RequestInit }[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit) => {
      seen.push({ url, body: String(init.body), init })
      return new Response(JSON.stringify({ access_token: 'narrow', token_type: 'Bearer' }),
        { status: 200, headers: { 'content-type': 'application/json' } })
    }))
    const got = await tokenForSp('FULL', 'https://aria.home.agience.ai/chat', 'https://origin.test')
    expect(got).toBe('narrow')
    expect(seen).toHaveLength(1)
    expect(seen[0].url).toBe('https://origin.test/auth/me/authority/narrow')
    expect(seen[0].init.credentials).toBe('include')
    expect(JSON.parse(seen[0].body)).toEqual({ audience: 'https://aria.home.agience.ai' })
    expect(seen[0].body).not.toContain('FULL')
  })

  it('hands nothing when Origin refuses, never the full token', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 400 })))
    await expect(tokenForSp('FULL', 'https://aria.home.agience.ai/', 'https://origin.test'))
      .rejects.toThrow()
  })

  it('keeps the platform app\'s own token for the platform app', async () => {
    const f = vi.fn()
    vi.stubGlobal('fetch', f)
    expect(await tokenForSp('FULL', 'https://my.agience.ai/', 'https://origin.test')).toBe('FULL')
    expect(f).not.toHaveBeenCalled()
  })
})
