/**
 * Review 11, H3: Crystal and the personas never receive the person's own token. Before the web
 * app calls Crystal it exchanges the token at Origin (RFC 8693): for a persona's own surface
 * (`/personas/{name}/...`) a delegation narrowed to that persona; for anything else Crystal does,
 * one narrowed to Crystal. If Origin will not issue one, the call carries nothing.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

import { crystalAudience, narrowedFor, resetNarrowedForTests } from '../narrowed'

afterEach(() => {
  vi.restoreAllMocks()
  resetNarrowedForTests()
})

describe('what the web app sends Crystal', () => {
  it('names the persona for its own surface, else Crystal', () => {
    expect(crystalAudience('/personas/iris/tools/call')).toBe('iris')
    expect(crystalAudience('/personas/lumen/resources/read')).toBe('lumen')
    expect(crystalAudience('/personas')).toBe('crystal')
    expect(crystalAudience('/artifacts/a-1/op/invoke')).toBe('crystal')
    expect(crystalAudience('/types/all')).toBe('crystal')
  })

  it('narrows once per audience in the session and keeps it until it nears expiry', async () => {
    const seen: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init: RequestInit) => {
      const asked = JSON.parse(String(init.body)) as { audience: string }
      seen.push(asked.audience)
      return new Response(JSON.stringify({ access_token: `for-${asked.audience}`,
        expires_in: 300 }), { status: 200, headers: { 'content-type': 'application/json' } })
    }))
    expect(await narrowedFor('FULL', 'iris', 'https://origin.test')).toBe('for-iris')
    expect(await narrowedFor('FULL', 'iris', 'https://origin.test')).toBe('for-iris')
    expect(await narrowedFor('FULL', 'crystal', 'https://origin.test')).toBe('for-crystal')
    expect(seen).toEqual(['iris', 'crystal'])
  })

  it('never falls back to the full token', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 400 })))
    await expect(narrowedFor('FULL', 'iris', 'https://origin.test')).rejects.toThrow()
  })
})
