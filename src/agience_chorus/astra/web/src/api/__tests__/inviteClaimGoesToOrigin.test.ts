/**
 * Review 12: an invite is claimed at Origin, in the claimant's Origin session, from its token
 * alone (`POST {ORIGIN_URI}/auth/me/authority/claim`), never through Mantle's `/grants/claim`.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

import api from '../api'
import { claimInvite } from '../artifacts'

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('an invite claim goes to Origin', () => {
  it('posts the token to Origin with the session and never to Mantle', async () => {
    const sent: { url: string; init: RequestInit }[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit) => {
      sent.push({ url, init })
      return new Response(JSON.stringify({ outcome: 'appended', seq: 3, resource_id: 'K' }),
                          { status: 200 })
    }))
    const mantle = vi.spyOn(api, 'post')
    const r = await claimInvite('tok-k')
    expect(mantle).not.toHaveBeenCalled()
    expect(sent).toHaveLength(1)
    expect(sent[0].url).toMatch(/\/auth\/me\/authority\/claim$/)
    expect(sent[0].init.credentials).toBe('include')
    expect((sent[0].init.headers as Record<string, string>)['X-Origin-Session']).toBe('1')
    expect(JSON.parse(String(sent[0].init.body))).toEqual({ token: 'tok-k' })
    expect(r.resource_id).toBe('K')
  })

  it('a refusal at Origin is an error, with nothing sent to Mantle', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: 'no live invite' }),
                                                          { status: 404 })))
    const mantle = vi.spyOn(api, 'post')
    await expect(claimInvite('nope')).rejects.toThrow(/404/)
    expect(mantle).not.toHaveBeenCalled()
  })
})
