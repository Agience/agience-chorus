/**
 * Review 14.
 *
 * M4: an invite names the item the owner has open, by the name the owner confirmed. Facet sends
 * Origin that name, and Origin echoes the item's id, the name and the address in its answer (and
 * puts them in its mail). An echo naming another item is refused here, so the owner never reads
 * "sent" for an invite to something else.
 *
 * Review 15, L3: Facet repairs no drop key. Only a holder of the collection key derives one, and
 * the browser holds none, so a repair would carry Mantle's word. A replacement is the operator's,
 * through Origin's console, after Origin's alert.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { afterEach, describe, expect, it, vi } from 'vitest'

import { createGrant } from '../collections'
import { previewAtOrigin } from '../authority'

type Sent = { url: string; method: string; body: Record<string, unknown> | null }

function originFetch(sent: Sent[], answer: (url: string) => unknown) {
  return vi.fn(async (url: string, init: RequestInit = {}) => {
    sent.push({ url, method: String(init.method || 'GET'),
                body: init.body ? JSON.parse(String(init.body)) : null })
    return new Response(JSON.stringify(answer(url)), { status: 200 })
  })
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('an invite names the item the owner has open, and Origin echoes it', () => {
  it('sends the owner-confirmed name and returns Origin\'s echo', async () => {
    const sent: Sent[] = []
    vi.stubGlobal('fetch', originFetch(sent, () => ({
      invite_id: 'inv-1', resource_id: 'W', resource_name: 'Plans', actions: ['read'],
      expires_at: null, email: 'bob@x.test' })))
    const g = await createGrant('W', { grantee_type: 'invite', can_read: true,
                                       target_entity: 'bob@x.test', resource_name: 'Plans',
                                       preview: 'P1' })
    expect(sent[0].body).toEqual({ resource_id: 'W', resource_name: 'Plans', actions: ['read'],
                                   email: 'bob@x.test', expires_at: null, preview: 'P1' })
    expect((g as unknown as { invite_echo: unknown }).invite_echo).toEqual(
      { resource_id: 'W', resource_name: 'Plans', email: 'bob@x.test' })
  })

  it('refuses an echo that names another item', async () => {
    vi.stubGlobal('fetch', originFetch([], () => ({
      invite_id: 'inv-1', resource_id: 'OTHER', resource_name: 'Plans', actions: ['read'],
      expires_at: null, email: 'bob@x.test' })))
    await expect(createGrant('W', { grantee_type: 'invite', can_read: true,
                                    target_entity: 'bob@x.test', resource_name: 'Plans' }))
      .rejects.toThrow(/another item/)
  })
})

describe('Facet repairs no drop key from what Mantle says (review 15, L3)', () => {
  it("has no repair path: a replacement is the operator's, after Origin's alert", async () => {
    const authority = await import('../authority')
    expect('repairDropKey' in authority).toBe(false)
    const root = resolve(__dirname, '../..')
    for (const f of ['api/authority.ts', 'components/modals/CollectionDetailModal.tsx']) {
      const text = readFileSync(resolve(root, f), 'utf8')
      expect(text).not.toMatch(/drop-key/)
    }
  })
})

// Review 15, L4: before an invite or grant is made, Origin answers with what it holds about the
// item (its parent chain and its grantees); the owner confirms that, and the make names it.
describe('Origin previews the item before an invite or grant is made', () => {
  it('reads the preview in the Origin session', async () => {
    const sent: Sent[] = []
    vi.stubGlobal('fetch', originFetch(sent, () => ({
      resource_id: 'W', parents: ['P'], grantees: [{ resource_id: 'W', grantee_id: 'ann',
        grantee_type: 'user', effect: 'allow', actions: ['read'], target_kind: null }],
      preview: 'D1' })))
    const p = await previewAtOrigin('W')
    expect(sent[0].url).toMatch(/\/auth\/me\/authority\/preview$/)
    expect(sent[0].body).toEqual({ resource_id: 'W' })
    expect(p.parents).toEqual(['P'])
    expect(p.preview).toBe('D1')
  })

  it('a direct grant names the preview too', async () => {
    const sent: Sent[] = []
    vi.stubGlobal('fetch', originFetch(sent, () => ({ grant_id: 'g-1', resource_id: 'W' })))
    await createGrant('W', { grantee_type: 'user', grantee_id: 'bob', can_read: true,
                             preview: 'D2' })
    expect(sent[0].body).toMatchObject({ resource_id: 'W', grantee_id: 'bob', preview: 'D2' })
  })
})
