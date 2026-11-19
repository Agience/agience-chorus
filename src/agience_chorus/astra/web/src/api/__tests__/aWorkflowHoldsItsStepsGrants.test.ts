/**
 * Whichever artifact holds a step holds that step's grants (FR-007). A workflow with inline steps
 * is itself the holder: as the person saves it, their Origin session gives the workflow Invoke on
 * each operator a step invokes and Read on each item a step links, unless the workflow holds it
 * already. Origin's ledger decides each; what it refuses is named, and nothing else is sent.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

import { holdStepGrants, stepNeeds } from '../stepGrants'

type Sent = { url: string; method: string; body: Record<string, unknown> | null }

const RUN = {
  type: 'workflow',
  steps: [
    { operator_id: 'op-read', arguments: { artifact_id: '@link.s1.artifact_id' } },
    { operator_id: 'op-raise', arguments: { container_id: '@link.s2.container_id', title: 'x' } },
    { operator_id: 'op-read', arguments: { artifact_id: '@link.s1.artifact_id' } },
  ],
}
const LINKS = { 's1.artifact_id': 'note-1', 's2.container_id': 'inbox-1' }

function origin(sent: Sent[], held: Record<string, unknown[]> = {}, refuse: string[] = []) {
  return vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = String(init.method || 'GET')
    const body = init.body ? JSON.parse(String(init.body)) : null
    sent.push({ url, method, body })
    if (method === 'GET') {
      const id = decodeURIComponent(url.split('resource_id=')[1] ?? '')
      return new Response(JSON.stringify({ grants: held[id] ?? [] }), { status: 200 })
    }
    if (refuse.includes(String(body?.resource_id))) {
      return new Response(JSON.stringify({ detail: 'you may not grant this' }), { status: 403 })
    }
    return new Response(JSON.stringify({ grant_id: `g-${body?.resource_id}` }), { status: 200 })
  })
}

const made = (sent: Sent[]) => sent.filter((s) => s.method === 'POST').map((s) => s.body)

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('a workflow holds its inline steps\' grants', () => {
  it('needs Invoke on each operator and Read on each linked item, once each', () => {
    expect(stepNeeds(RUN, LINKS)).toEqual([
      ['op-read', 'invoke'], ['note-1', 'read'], ['op-raise', 'invoke'], ['inbox-1', 'read'],
    ])
    expect(stepNeeds({ type: 'mcp_tool' }, LINKS)).toEqual([])
    expect(stepNeeds(undefined, LINKS)).toEqual([])
  })

  it('the person gives the workflow each grant it lacks, as an artifact grantee', async () => {
    const sent: Sent[] = []
    vi.stubGlobal('fetch', origin(sent))
    expect(await holdStepGrants('wf', RUN, LINKS)).toEqual([])
    expect(made(sent)).toEqual([
      expect.objectContaining({ resource_id: 'op-read', grantee_id: 'wf', grantee_type: 'artifact', actions: ['invoke'] }),
      expect.objectContaining({ resource_id: 'note-1', grantee_id: 'wf', grantee_type: 'artifact', actions: ['read'] }),
      expect.objectContaining({ resource_id: 'op-raise', grantee_id: 'wf', grantee_type: 'artifact', actions: ['invoke'] }),
      expect.objectContaining({ resource_id: 'inbox-1', grantee_id: 'wf', grantee_type: 'artifact', actions: ['read'] }),
    ])
    expect(sent.every((s) => s.url.includes('/auth/me/authority/grants'))).toBe(true)
  })

  it('a grant the workflow holds already is not made again; a revoked or denied one is', async () => {
    const sent: Sent[] = []
    const row = (id: string, extra: Record<string, unknown> = {}) => ({
      grant_id: `h-${id}`, grantee_id: 'wf', grantee_type: 'artifact', resource_id: id,
      actions: [id.startsWith('op') ? 'invoke' : 'read'], state: 'active', effect: 'allow', ...extra })
    vi.stubGlobal('fetch', origin(sent, {
      'op-read': [row('op-read')], 'note-1': [row('note-1')],
      'op-raise': [row('op-raise', { state: 'revoked' })], 'inbox-1': [row('inbox-1', { effect: 'deny' })],
    }))
    await holdStepGrants('wf', RUN, LINKS)
    expect(made(sent).map((b) => b?.resource_id)).toEqual(['op-raise', 'inbox-1'])
  })

  it('a grant someone else holds is not the workflow\'s', async () => {
    const sent: Sent[] = []
    vi.stubGlobal('fetch', origin(sent, { 'op-read': [{ grant_id: 'u', grantee_id: 'alice',
      grantee_type: 'user', actions: ['invoke'], state: 'active' }] }))
    await holdStepGrants('wf', { type: 'workflow', steps: [{ operator_id: 'op-read' }] }, {})
    expect(made(sent).map((b) => b?.resource_id)).toEqual(['op-read'])
  })

  it('what Origin refuses is named, and the rest are still made', async () => {
    const sent: Sent[] = []
    vi.stubGlobal('fetch', origin(sent, {}, ['note-1']))
    expect(await holdStepGrants('wf', RUN, LINKS)).toEqual(['note-1'])
    expect(made(sent).map((b) => b?.resource_id)).toEqual(['op-read', 'note-1', 'op-raise', 'inbox-1'])
  })

  it('the workflow never grants itself', async () => {
    const sent: Sent[] = []
    vi.stubGlobal('fetch', origin(sent))
    await holdStepGrants('wf', { type: 'workflow', steps: [{ operator_id: 'wf' }] }, {})
    expect(sent).toEqual([])
  })
})
