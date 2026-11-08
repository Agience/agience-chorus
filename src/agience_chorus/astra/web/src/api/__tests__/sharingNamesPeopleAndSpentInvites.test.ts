/**
 * Origin's sharing record names the people an owner shares with (their display name at Origin,
 * the same record the preview names creators from) and says how many times an invite was claimed.
 * Facet carries both: a member shows by name, and an invite whose claims are spent is not listed
 * as waiting.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

import { listGrants } from '../collections'

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('the sharing record', () => {
  it('carries a member\'s name and an invite\'s claims from Origin', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ grants: [
      { grant_id: 'g-bob', grantee_id: 'bob-1', grantee_type: 'user', resource_id: 'W',
        actions: ['read'], state: 'active', grantee_name: 'Bob' },
      { grant_id: 'inv-1', grantee_id: 'x', grantee_type: 'invite', resource_id: 'W',
        actions: ['read'], state: 'active', target_kind: 'email', max_claims: 1, claims: 1 },
    ] }), { status: 200 })))
    const [bob, inv] = await listGrants('W')
    expect(bob.name).toBe('Bob')
    expect(inv.max_claims).toBe(1)
    expect(inv.claims_count).toBe(1)
  })
})
