/**
 * Review 12, John's decision 1: authority changes happen at Origin.
 *
 * The token the web app sends Mantle reads and writes content and changes no authority. A grant, an
 * invite, a deny, or a change to one goes from here straight to Origin, in the person's Origin
 * session: `POST {ORIGIN_URI}/auth/me/authority/entries` with `{entry}`, the session cookie
 * (`credentials: 'include'`) and the `X-Origin-Session` header Origin's CSRF check requires. Origin
 * decides it by the ledger's rules as the person's own entry; Mantle applies it from Origin's feed.
 *
 * An invite's claim token is made here, in the browser, and Origin sees only its SHA-256 (the
 * invite's grantee) and the digest of its target, as the ledger stores them.
 */
import { getRuntimeConfig } from '../config/runtime'
import type { GrantResponse } from './types/grant'

/** CRUDEASIO, in the ledger's order. */
export const ACTIONS = ['create', 'read', 'update', 'delete', 'evict', 'invoke', 'add', 'share',
  'admin'] as const

export type Flags = Partial<Record<`can_${(typeof ACTIONS)[number]}`, boolean>>

export interface LedgerGrant {
  kind: 'grant'
  grant_id: string
  grantee_id: string
  grantee_type: string
  resource_id: string
  actions: string[]
  effect: 'allow' | 'deny'
  state: string
  expires_at: string | null
  target: { kind: string; digest: string } | null
  max_claims: number | null
}

export class AuthorityRefused extends Error {
  constructor(public status: number, detail: string) {
    super(`Origin refused the change (${status}): ${detail}`)
  }
}

export function actionsOf(flags: Flags | Record<string, unknown>): string[] {
  return ACTIONS.filter((a) => Boolean((flags as Record<string, unknown>)[`can_${a}`]))
}

async function sha256hex(s: string): Promise<string> {
  const d = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s))
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, '0')).join('')
}

/** The ledger's digest of an invite's target (Origin's `authority_ledger.target_digest`). */
export async function targetDigest(kind: string, value: string): Promise<string> {
  let v = value.trim()
  if (kind === 'email' || kind === 'domain') v = v.toLowerCase()
  return sha256hex(`agience-invite-target:${kind}:${v}`)
}

/** Send one ledger entry to Origin in the person's Origin session. */
export async function submitAuthorityEntry(entry: LedgerGrant): Promise<Record<string, unknown>> {
  const origin = getRuntimeConfig().originUri.replace(/\/$/, '')
  const r = await fetch(`${origin}/auth/me/authority/entries`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', 'X-Origin-Session': '1' },
    body: JSON.stringify({ entry }),
  })
  if (!r.ok) {
    let detail = ''
    try { detail = String(((await r.json()) as { detail?: unknown }).detail ?? '') } catch { /* none */ }
    throw new AuthorityRefused(r.status, detail)
  }
  return (await r.json()) as Record<string, unknown>
}

/** Claim an invite at Origin, in the claimant's Origin session, from its token alone: Origin finds
 *  the invite by the token's digest and makes the claim by the ledger's claim rule. */
export async function claimInviteAtOrigin(token: string): Promise<Record<string, unknown>> {
  const origin = getRuntimeConfig().originUri.replace(/\/$/, '')
  const r = await fetch(`${origin}/auth/me/authority/claim`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', 'X-Origin-Session': '1' },
    body: JSON.stringify({ token }),
  })
  if (!r.ok) {
    let detail = ''
    try { detail = String(((await r.json()) as { detail?: unknown }).detail ?? '') } catch { /* none */ }
    throw new AuthorityRefused(r.status, detail)
  }
  return (await r.json()) as Record<string, unknown>
}

export interface GrantInput extends Flags {
  grantee_type?: string
  grantee_id?: string
  target_entity?: string
  target_entity_type?: string
  max_claims?: number
  expires_at?: string
  effect?: 'allow' | 'deny'
  /** An invite's item, by the name the owner confirmed; Origin puts it in the mail and echoes it. */
  resource_name?: string
  /** The digest of Origin's preview the owner confirmed (review 15); Origin refuses a make that
   *  names none, or one that no longer matches what it holds. */
  preview?: string
}

/** What Origin holds about an item, shown to the owner before an invite or grant is made on it
 *  (review 15, L4): its parent chain (ids, nearest first) and the active grants on it and on those
 *  parents. `preview` is the digest a make names. */
export interface OriginPreview {
  resource_id: string
  parents: string[]
  /** Beside each parent id, what a person recognizes (review 16): who made it, as their display
   *  name at Origin, and when. Origin holds no item names. */
  parent_details?: { id: string; creator: string; created_at: string | null }[]
  /** The item itself (review 17): who made it, when, and how many members and grants it has. */
  resource_detail?: { id: string; creator: string; created_at: string | null; members: number
                      grantees: number }
  /** A person grantee carries their display name at Origin (`grantee_name`). */
  grantees: { resource_id: string; grantee_id: string; grantee_type: string; effect: string
              actions: string[]; target_kind?: string | null; grantee_name?: string }[]
  preview: string
}

/** A parent as Origin holds it: its id, who made it and on what day. */
export function describeParent(p: OriginPreview, id: string): string {
  const d = (p.parent_details || []).find((x) => x.id === id)
  if (!d) return id
  const day = d.created_at ? d.created_at.slice(0, 10) : 'an unknown day'
  return `${id} (made by ${d.creator || 'someone'} on ${day})`
}

/** A grantee in Origin's preview, in words: an invite, or a person by name where Origin has one. */
export function describeGrantee(g: OriginPreview['grantees'][number]): string {
  if (g.grantee_type === 'invite') return 'an invite'
  const id = g.grantee_id.slice(0, 8)
  return g.grantee_name ? `${g.grantee_name} (${id})` : `Someone (${id})`
}

/** The item itself as Origin holds it, in words. */
export function describeItem(p: OriginPreview): string {
  const d = p.resource_detail
  if (!d) return p.resource_id
  const day = d.created_at ? d.created_at.slice(0, 10) : 'an unknown day'
  return `${d.id}, made by ${d.creator || 'someone'} on ${day}, with ${d.members} members and `
    + `${d.grantees} grants`
}

export async function previewAtOrigin(resourceId: string): Promise<OriginPreview> {
  return (await session('POST', '/preview', { resource_id: resourceId })) as OriginPreview
}

/** What Origin says it invited to, and whom (review 14, M4). */
export interface InviteEcho {
  resource_id: string
  resource_name: string
  email: string
}

/** A grant as Origin's own record holds it (`GET /auth/me/authority/grants`). */
interface OriginGrant {
  grant_id: string
  grantee_id: string
  grantee_type: string
  resource_id?: string
  actions: string[]
  effect?: string
  state?: string
  expires_at?: string | null
  target_kind?: string | null
  /** A person grantee's display name at Origin. */
  grantee_name?: string
  /** An invite's claims so far, and how many it allows. */
  claims?: number
  max_claims?: number | null
}

/** Marks a grant row Facet read from Origin's own record. A row without it (one Mantle listed)
 *  never names a change (round 13, H2). */
const FROM_ORIGIN = '__fromOrigin'

async function session(method: string, path: string, body?: unknown): Promise<unknown> {
  const origin = getRuntimeConfig().originUri.replace(/\/$/, '')
  const r = await fetch(`${origin}/auth/me/authority${path}`, {
    method,
    credentials: 'include',
    headers: body === undefined
      ? { 'X-Origin-Session': '1' }
      : { 'Content-Type': 'application/json', 'X-Origin-Session': '1' },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  })
  if (!r.ok) {
    let detail = ''
    try { detail = String(((await r.json()) as { detail?: unknown }).detail ?? '') } catch { /* none */ }
    throw new AuthorityRefused(r.status, detail)
  }
  return r.json()
}

function asGrant(g: OriginGrant, resourceId: string): GrantResponse {
  const flags = Object.fromEntries(ACTIONS.map((a) => [`can_${a}`, (g.actions || []).includes(a)]))
  return {
    id: g.grant_id, resource_id: g.resource_id ?? resourceId, grantee_type: g.grantee_type,
    grantee_id: g.grantee_id, state: g.state ?? 'active', effect: g.effect ?? 'allow',
    expires_at: g.expires_at ?? null, target_entity_type: g.target_kind ?? null, ...flags,
    ...(g.grantee_name ? { name: g.grantee_name } : {}),
    ...(g.grantee_type === 'invite'
      ? { claims_count: Number(g.claims ?? 0), max_claims: g.max_claims ?? null } : {}),
    [FROM_ORIGIN]: true,
  } as unknown as GrantResponse
}

/** The grants on a resource, as Origin's own record holds them, read in the Origin session. */
export async function listGrantsAtOrigin(resourceId: string): Promise<GrantResponse[]> {
  const body = (await session('GET', `/grants?resource_id=${encodeURIComponent(resourceId)}`)) as
    { grants?: OriginGrant[] } | OriginGrant[]
  const rows = Array.isArray(body) ? body : (body.grants ?? [])
  return rows.map((g) => asGrant(g, resourceId))
}

function originGrantId(prior: GrantResponse): string {
  const p = prior as unknown as Record<string, unknown>
  if (!p[FROM_ORIGIN] || !p.id) {
    throw new AuthorityRefused(409, 'a change names a grant read from the record Origin keeps, '
      + 'never a row Mantle listed')
  }
  return String(p.id)
}

/** A grant made at Origin, which picks its id; or an invite Origin makes for one address and mails
 *  itself. An invite with no address is not made. */
export async function makeGrant(resourceId: string, input: GrantInput): Promise<GrantResponse> {
  const direct = (input.grantee_type ?? (input.grantee_id ? 'user' : 'invite')) !== 'invite'
    && Boolean(input.grantee_id)
  const actions = actionsOf(input)
  if (direct) {
    const made = (await session('POST', '/grants', {
      resource_id: resourceId, grantee_id: String(input.grantee_id), actions,
      effect: input.effect ?? 'allow', expires_at: input.expires_at ?? null,
      ...(input.preview ? { preview: input.preview } : {}),
    })) as OriginGrant
    return asGrant({ ...made, grantee_type: made.grantee_type ?? 'user',
                     actions: made.actions ?? actions,
                     grantee_id: made.grantee_id ?? String(input.grantee_id) }, resourceId)
  }
  const email = (input.target_entity || '').trim()
  if (!email || (input.target_entity_type && input.target_entity_type !== 'email')) {
    throw new AuthorityRefused(400, 'an invite is made for one email address, which Origin mails')
  }
  const made = (await session('POST', '/invites', {
    resource_id: resourceId,
    ...(input.resource_name ? { resource_name: input.resource_name } : {}),
    actions, email, expires_at: input.expires_at ?? null,
    ...(input.preview ? { preview: input.preview } : {}),
  })) as { invite_id: string; actions?: string[]; expires_at?: string | null
           resource_id?: string; resource_name?: string; email?: string }
  // Origin's echo names the item it invited to (review 14, M4). One naming another item is never
  // reported as sent: the owner is told, and revokes it.
  if (made.resource_id !== undefined && made.resource_id !== resourceId) {
    throw new AuthorityRefused(409, `Origin's invite names another item (${made.resource_id}), `
      + `not ${resourceId}: revoke it`)
  }
  const g = asGrant({ grant_id: made.invite_id, grantee_id: '', grantee_type: 'invite',
                      actions: made.actions ?? actions, expires_at: made.expires_at ?? null,
                      target_kind: 'email' }, resourceId)
  const invite_echo: InviteEcho = { resource_id: made.resource_id ?? resourceId,
                                    resource_name: made.resource_name ?? input.resource_name ?? '',
                                    email: made.email ?? email }
  return { ...g, target_entity: email, max_claims: 1, invite_echo } as GrantResponse
}

/** A grant Origin listed, changed to these actions: Origin builds the entry from its own record,
 *  so Facet states no grantee, resource or prior actions. */
export async function changeGrant(prior: GrantResponse, updates: GrantInput & { state?: string })
  : Promise<GrantResponse> {
  const id = originGrantId(prior)
  if (updates.state === 'revoked') {
    await session('POST', `/grants/${encodeURIComponent(id)}/revoke`)
    return { ...prior, state: 'revoked' } as GrantResponse
  }
  const merged = { ...(prior as unknown as Record<string, unknown>), ...updates }
  const actions = actionsOf(merged)
  await session('POST', `/grants/${encodeURIComponent(id)}/change`, {
    actions, expires_at: (merged.expires_at as string) ?? null,
  })
  return { ...(merged as object) } as unknown as GrantResponse
}

/** A grant Origin listed, revoked at Origin. */
export async function revokeGrant(prior: GrantResponse): Promise<void> {
  await changeGrant(prior, { state: 'revoked' })
}

/** An invite sent again: a new invite for the same address and actions, which Origin mails, and the
 *  old one revoked. */
export async function resendInviteAtOrigin(prior: GrantResponse, address?: string,
                                           preview?: string)
  : Promise<GrantResponse> {
  originGrantId(prior)
  // Origin keeps only the address's digest, so the owner names it again, and confirms Origin's
  // preview of the item again (review 15).
  const email = String(address || (prior as unknown as Record<string, unknown>).target_entity || '')
  const again = await makeGrant(prior.resource_id, { ...(prior as unknown as GrantInput),
                                                     grantee_type: 'invite', target_entity: email,
                                                     preview })
  await revokeGrant(prior)
  return again
}

/** What an invite grants and whether it is addressed to this person, read from Origin in the
 *  person's Origin session. The token goes to Origin only, never to Mantle. */
export interface InviteContext {
  invite_id?: string; resource_id?: string; actions?: string[]; expires_at?: string | null
  state?: string; for_you?: boolean
  /** Whether the signed-in person's own address is verified: an invite matches only a verified
   *  address. */
  address_verified?: boolean
}

export async function inviteContext(token: string): Promise<InviteContext> {
  return (await session('POST', '/invite-context', { token })) as InviteContext
}

/** A live invite that names the signed-in person (their id or their verified address), as Origin
 *  lists it in their Origin session (FR-004). Origin keeps no name for what is shared. */
export interface IncomingInvite {
  invite_id: string
  resource_id: string
  actions: string[]
  expires_at?: string | null
  /** The sender's display name at Origin. */
  from: string
}

export async function incomingInvites(): Promise<IncomingInvite[]> {
  const r = (await session('GET', '/invites/incoming')) as { invites?: IncomingInvite[] }
  return r.invites ?? []
}

/** Accept an invite in the app: the same claim as the mailed link, proven by the Origin session. */
export async function acceptInvite(inviteId: string): Promise<Record<string, unknown>> {
  return (await session('POST', `/invites/${encodeURIComponent(inviteId)}/accept`, {})) as
    Record<string, unknown>
}

/** Decline an invite in the app: Origin retires it, and its sender sees it declined. */
export async function declineInvite(inviteId: string): Promise<Record<string, unknown>> {
  return (await session('POST', `/invites/${encodeURIComponent(inviteId)}/decline`, {})) as
    Record<string, unknown>
}
