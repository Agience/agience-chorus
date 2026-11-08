/**
 * Round 13 (H1, H2): the person's view of grants, and the prior state of every change, come from
 * Origin's own record, read in the person's Origin session. A row Mantle lists never feeds an
 * authority change: Facet names only grants Origin listed, Origin builds every entry from its own
 * record, and Facet sends no grant id, grantee, resource or prior actions of its own making. An
 * invite is made at Origin for one address, which Origin mails; Facet never holds its link. The
 * claim page reads an invite's context from Origin, never from Mantle.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { afterEach, describe, expect, it, vi } from 'vitest'

import api from '../api'
import { createGrant, deleteGrant, listGrants, updateGrant } from '../collections'
import { inviteContext } from '../authority'

type Sent = { url: string; method: string; body: Record<string, unknown> | null }

function originFetch(sent: Sent[], answer: (url: string) => unknown = () => ({ outcome: 'appended' })) {
  return vi.fn(async (url: string, init: RequestInit = {}) => {
    sent.push({ url, method: String(init.method || 'GET'),
                body: init.body ? JSON.parse(String(init.body)) : null })
    return new Response(JSON.stringify(answer(url)), { status: 200 })
  })
}

const ORIGIN_ROWS = {
  grants: [{ grant_id: 'g-real', grantee_id: 'mal', grantee_type: 'user', resource_id: 'W',
             actions: ['read'], effect: 'allow', state: 'active', expires_at: null,
             target_kind: null }],
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('grants come from Origin\'s own record', () => {
  it('the list of grants is Origin\'s, read in the Origin session, never Mantle\'s /grants', async () => {
    const sent: Sent[] = []
    vi.stubGlobal('fetch', originFetch(sent, () => ORIGIN_ROWS))
    const mantle = vi.spyOn(api, 'get')
    const rows = await listGrants('W')
    expect(mantle).not.toHaveBeenCalled()
    expect(sent[0].url).toMatch(/\/auth\/me\/authority\/grants\?resource_id=W$/)
    expect(rows.map((g) => [g.id, g.grantee_id, g.can_read, g.can_admin]))
      .toEqual([['g-real', 'mal', true, false]])
  })

  it('a row Mantle listed is never revoked or changed: nothing is sent', async () => {
    const sent: Sent[] = []
    vi.stubGlobal('fetch', originFetch(sent))
    const listed = { id: 'g-decoy', grantee_type: 'user', grantee_id: 'mal', resource_id: 'W',
                     can_read: true, state: 'active' }
    await expect(deleteGrant(listed as never)).rejects.toThrow(/Origin/)
    await expect(updateGrant(listed as never, { can_read: true } as never)).rejects.toThrow(/Origin/)
    expect(sent).toEqual([])
  })

  it('a revocation names Origin\'s grant id and carries no entry', async () => {
    const sent: Sent[] = []
    vi.stubGlobal('fetch', originFetch(sent, (u) => (u.includes('?resource_id') ? ORIGIN_ROWS : {})))
    const [row] = await listGrants('W')
    await deleteGrant(row)
    expect(sent[1].url).toMatch(/\/auth\/me\/authority\/grants\/g-real\/revoke$/)
    expect(sent[1].body).toBeNull()
  })

  it('a change sends only the new actions; Origin builds the entry from its own record', async () => {
    const sent: Sent[] = []
    vi.stubGlobal('fetch', originFetch(sent, (u) => (u.includes('?resource_id') ? ORIGIN_ROWS : {})))
    const [row] = await listGrants('W')
    await updateGrant(row, { can_read: true, can_update: true } as never)
    expect(sent[1].url).toMatch(/\/auth\/me\/authority\/grants\/g-real\/change$/)
    expect(sent[1].body).toEqual({ actions: ['read', 'update'], expires_at: null })
  })

  it('a new grant is made at Origin, which picks its id', async () => {
    const sent: Sent[] = []
    vi.stubGlobal('fetch', originFetch(sent, () => ({ grant_id: 'g-new', resource_id: 'W',
                                                      grantee_id: 'bob', actions: ['read'] })))
    const g = await createGrant('W', { grantee_type: 'user', grantee_id: 'bob', can_read: true })
    expect(sent[0].url).toMatch(/\/auth\/me\/authority\/grants$/)
    expect(sent[0].body).toEqual({ resource_id: 'W', grantee_id: 'bob', actions: ['read'],
                                   effect: 'allow', expires_at: null })
    expect(g.id).toBe('g-new')
  })

  it('an invite names one address and is mailed by Origin; Facet never holds its link', async () => {
    const sent: Sent[] = []
    vi.stubGlobal('fetch', originFetch(sent, () => ({ invite_id: 'inv-1', resource_id: 'W',
                                                      actions: ['read'], expires_at: null })))
    await expect(createGrant('W', { grantee_type: 'invite', can_read: true })).rejects.toThrow(/address/)
    expect(sent).toEqual([])
    const g = await createGrant('W', { grantee_type: 'invite', can_read: true,
                                       target_entity: 'bob@x.test' })
    expect(sent[0].url).toMatch(/\/auth\/me\/authority\/invites$/)
    expect(sent[0].body).toEqual({ resource_id: 'W', actions: ['read'], email: 'bob@x.test',
                                   expires_at: null })
    expect((g as unknown as Record<string, unknown>).claim_token).toBeUndefined()
    expect(g.target_entity).toBe('bob@x.test')
  })

  it('the claim page reads an invite\'s context from Origin; no raw token reaches Mantle', async () => {
    const sent: Sent[] = []
    vi.stubGlobal('fetch', originFetch(sent, () => ({ invite_id: 'inv-1', resource_id: 'W',
                                                      actions: ['read'], state: 'active',
                                                      for_you: true })))
    const ctx = await inviteContext('tok-1')
    expect(sent[0].url).toMatch(/\/auth\/me\/authority\/invite-context$/)
    expect(sent[0].body).toEqual({ token: 'tok-1' })
    expect(ctx.for_you).toBe(true)
    const page = readFileSync(resolve(__dirname, '../../pages/InviteClaimPage.tsx'), 'utf8')
    expect(page).not.toMatch(/\/grants\/invite-/)
  })
})
