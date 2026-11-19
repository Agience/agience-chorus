/**
 * FR-004: an invite is an artifact. The inviter's Inbox records it and Origin lets the invitee
 * read it; accepting and declining are taken in the person's own Origin session, at the path the
 * invite's type names, never through Crystal.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

const postMock = vi.fn()
const sessionMock = vi.fn()
vi.mock('../api', () => ({ post: (...a: unknown[]) => postMock(...a) }))
vi.mock('../authority', () => ({ session: (...a: unknown[]) => sessionMock(...a) }))
vi.mock('../workspaces', () => ({
  listWorkspaces: async () => [{ id: 'ws1' }, { id: 'inbox1', inbox: true }],
}))

import { actOnInvite, INVITE_CONTENT_TYPE, offeredInvites, recordInvite } from '../inviteArtifacts'

beforeEach(() => {
  postMock.mockReset()
  sessionMock.mockReset()
})

describe('invite artifacts', () => {
  it('records the invite in the Inbox and retries Origin until it has seen the artifact', async () => {
    postMock.mockResolvedValue({ id: 'a1' })
    sessionMock.mockRejectedValueOnce(Object.assign(new Error('not yet'), { status: 409 }))
      .mockResolvedValueOnce({ recorded: true })
    expect(await recordInvite('inv-1', [0, 0])).toBe('a1')
    expect(postMock).toHaveBeenCalledWith('/create', {
      content_type: INVITE_CONTENT_TYPE, invite_id: 'inv-1', container_id: 'inbox1' })
    expect(sessionMock).toHaveBeenCalledTimes(2)
    expect(sessionMock).toHaveBeenLastCalledWith('POST', '/invites/inv-1/record',
                                                 { artifact_id: 'a1' })
  })

  it('gives up on a refusal that is not a retry', async () => {
    postMock.mockResolvedValue({ id: 'a1' })
    sessionMock.mockRejectedValue(Object.assign(new Error('no'), { status: 403 }))
    await expect(recordInvite('inv-1', [0, 0])).rejects.toThrow('no')
    expect(sessionMock).toHaveBeenCalledTimes(1)
  })

  it('lists the invites through the Inbox operation', async () => {
    postMock.mockResolvedValue({ items: [{ id: 'a1', invite_id: 'inv-1' }] })
    expect(await offeredInvites()).toEqual([{ id: 'a1', invite_id: 'inv-1' }])
    expect(postMock).toHaveBeenCalledWith('/artifacts/inbox1/op/invites', {})
  })

  it('takes the named path in the Origin session', async () => {
    postMock.mockResolvedValue({ detail: { origin_session: {
      method: 'POST', path: '/auth/me/authority/invites/inv-1/accept' } } })
    sessionMock.mockResolvedValue({ grant_id: 'g1' })
    expect(await actOnInvite('a1', 'accept')).toEqual({ grant_id: 'g1' })
    expect(postMock.mock.calls[0][0]).toBe('/artifacts/a1/op/accept')
    expect(sessionMock).toHaveBeenCalledWith('POST', '/invites/inv-1/accept', {})
  })

  it('refuses a path outside the Origin authority session', async () => {
    postMock.mockResolvedValue({ detail: { origin_session: { method: 'POST', path: '/admin/x' } } })
    await expect(actOnInvite('a1', 'decline')).rejects.toThrow(/no decline path/)
    expect(sessionMock).not.toHaveBeenCalled()
  })
})
