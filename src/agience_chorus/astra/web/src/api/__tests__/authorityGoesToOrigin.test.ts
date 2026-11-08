/**
 * Review 12, John's decision 1: authority changes happen at Origin.
 *
 * The web app sends Mantle a token that reads and writes content but changes no authority. A grant,
 * an invite, a deny or its revocation goes from the web app straight to Origin, in the person's
 * Origin session (`POST {ORIGIN_URI}/auth/me/authority/entries`, `credentials: 'include'`, header
 * `X-Origin-Session`), as a ledger entry. Mantle applies it from Origin's feed. An invite's claim
 * token is made here and only its digest goes to Origin. Nothing of it goes to Mantle's `/grants`.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

import api from '../api'
import { createGrant } from '../collections'

type Sent = { url: string; init: RequestInit; entry: Record<string, unknown> }

function originFetch(sent: Sent[], status = 200) {
  return vi.fn(async (url: string, init: RequestInit) => {
    const body = JSON.parse(String(init.body))
    sent.push({ url, init, entry: body.entry })
    return new Response(JSON.stringify({ outcome: 'appended', seq: 1 }), { status })
  })
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('authority goes to Origin, in the person\'s Origin session', () => {
  // Round 13: what each change sends Origin, and that a row Mantle listed sends nothing, is in
  // grantsComeFromOrigin.test.ts.
  it('Origin\'s refusal is the caller\'s error, and nothing falls back to Mantle', async () => {
    const sent: Sent[] = []
    vi.stubGlobal('fetch', originFetch(sent, 403))
    const mantle = vi.spyOn(api, 'post')
    await expect(createGrant('col-1', { grantee_type: 'user', grantee_id: 'bob',
                                        can_read: true })).rejects.toThrow()
    expect(mantle).not.toHaveBeenCalled()
  })
})
