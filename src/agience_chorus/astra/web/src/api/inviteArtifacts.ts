// An invite is an artifact (FR-004). Origin makes the invite in the inviter's Origin session; the
// inviter's own Inbox then holds an artifact recording it, which Crystal fills from Origin's own
// row, and Origin lets the invitee read that artifact. The invitee's Inbox lists the invites made
// for them through the workspace type's `invites` operation. Accepting and declining change
// authority, so the invite type names the Origin path for each and the person's own Origin session
// takes it.
import { post } from './api'
import { session } from './authority'
import { listWorkspaces } from './workspaces'

export const INVITE_CONTENT_TYPE = 'application/vnd.agience.grant-invite+json'

/** An invite made for the signed-in person, as its artifact records it. */
export interface OfferedInvite {
  /** The invite artifact. */
  id: string
  invite_id: string
  resource_id: string
  resource_name?: string
  actions: string[]
  expires_at?: string | null
  /** Who made the invite. */
  from?: string
}

let inbox: Promise<string> | null = null

/** The caller's Inbox workspace id, found once per page load. */
export function myInboxId(): Promise<string> {
  if (!inbox) {
    inbox = listWorkspaces()
      .then((ws) => {
        const id = ws.find((w) => w.inbox)?.id
        if (!id) throw new Error('no Inbox listed')
        return id
      })
      .catch((err) => { inbox = null; throw err })
  }
  return inbox
}

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

/** Record the invite `inviteId` as an artifact in the inviter's Inbox, and ask Origin to let its
 *  invitee read it. Origin answers 409 until its feed has seen the new artifact, so that is
 *  retried a few times. */
export async function recordInvite(inviteId: string, delays = [500, 1000, 2000, 4000]):
    Promise<string> {
  const made = await post<{ id: string }>('/create', {
    content_type: INVITE_CONTENT_TYPE, invite_id: inviteId, container_id: await myInboxId(),
  })
  for (let i = 0; ; i++) {
    try {
      await session('POST', `/invites/${encodeURIComponent(inviteId)}/record`,
                    { artifact_id: made.id })
      return made.id
    } catch (e) {
      const status = (e as { status?: number }).status
      if (status !== 409 || i >= delays.length) throw e
      await wait(delays[i])
    }
  }
}

/** The invites made for the signed-in person and still waiting. */
export async function offeredInvites(): Promise<OfferedInvite[]> {
  const id = await myInboxId()
  const r = await post<{ items?: OfferedInvite[] }>(
    `/artifacts/${encodeURIComponent(id)}/op/invites`, {})
  return r?.items ?? []
}

/** Carry out the invite type's `op` (accept or decline) on the invite artifact `artifactId`:
 *  Crystal names the Origin path, and the person's own Origin session takes it. */
export async function actOnInvite(artifactId: string, op: 'accept' | 'decline'):
    Promise<Record<string, unknown>> {
  const named = await post<{ detail?: { origin_session?: { method?: string; path?: string } } }>(
    `/artifacts/${encodeURIComponent(artifactId)}/op/${op}`, {},
    { validateStatus: (s: number) => s === 409 })
  const path = named?.detail?.origin_session?.path ?? ''
  const prefix = '/auth/me/authority'
  if (!path.startsWith(prefix + '/')) throw new Error(`the invite names no ${op} path`)
  return (await session(named.detail!.origin_session!.method ?? 'POST', path.slice(prefix.length),
                        {})) as Record<string, unknown>
}
