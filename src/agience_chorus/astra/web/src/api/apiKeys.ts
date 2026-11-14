// Grant keys — the platform's bearer credentials for non-interactive callers.
//
// ⛔ THIS SPOKE `/api-keys`, AND NO SERVICE HAS EVER SERVED IT. Mantle publishes `/grants/keys`;
// `/api-keys` answered 404 on mantle, origin and crystal alike, so every function here failed.
// Measured 2026-09-13. The suite did not notice because it mocks the transport: `apiKeys.test.ts`
// asserts which URL was passed, which is a claim about intent rather than about the server.
//
// ⚠ IT IS NOT A RENAME — THE MODEL CHANGED. An API key carried `scopes[]`, `resource_filters{}`
// and `is_active`; a grant key carries CAPABILITY FLAGS (`can_read`, `can_update`, `can_admin`, …),
// a `state`, and a `resource_id` naming what it is a grant OVER. A scope list cannot be translated
// field-for-field into capabilities, so nothing here pretends to: callers name the capabilities
// they want.
//
// ⚠ THERE IS NO UPDATE. Mantle serves POST, GET, GET/{id} and DELETE/{id} on `/grants/keys` and no
// PATCH, so the `updateAPIKey` that used to live here described an operation the platform does not
// offer. A grant is revoked and reissued rather than edited — `key` is shown once and cannot be
// re-read, so editing one in place would have no way to return a usable credential.

import api from './api';
import { askOrigin } from './jobGrants';

/** How long a key may live (John, 2026-11-14). */
export const KEY_MAX_DAYS = 90;

/** What each access level a view names carries, as CRUDEASIO action names. */
const ROLE_ACTIONS: Record<'viewer' | 'editor' | 'collaborator', string[]> = {
  viewer: ['read'],
  editor: ['create', 'read', 'update', 'delete', 'evict'],
  collaborator: ['create', 'read', 'update', 'delete', 'evict', 'invoke', 'add', 'share'],
};

/** Capabilities a grant may carry. Absent means "not granted" — there is no inherited default. */
export interface GrantCapabilities {
  can_create?: boolean | null;
  can_read?: boolean | null;
  can_update?: boolean | null;
  can_delete?: boolean | null;
  can_evict?: boolean | null;
  can_invoke?: boolean | null;
  can_add?: boolean | null;
  can_share?: boolean | null;
  can_admin?: boolean | null;
}

export interface GrantKey extends GrantCapabilities {
  id: string;
  name: string;
  /** What the grant is over. Null for a grant not scoped to one artifact. */
  resource_id?: string | null;
  grantee_id?: string | null;
  grantee_type?: string | null;
  /** `active`, `revoked`, … — this replaces the old `is_active` boolean. */
  state: string;
  /** A non-secret fragment, for recognising a key whose secret is unrecoverable. */
  key_hint?: string | null;
  notes?: string | null;
  expires_at?: string | null;
  created_time: string;
  modified_time?: string | null;
  last_used_at?: string | null;
  revoked_at?: string | null;
  revoked_by?: string | null;
  max_claims?: number | null;
  claims_count?: number | null;
  members?: unknown[];
}

export interface GrantKeyCreateRequest extends GrantCapabilities {
  name: string;
  resource_id?: string | null;
  role?: string | null;
  expires_at?: string | null;
  notes?: string | null;
}

export interface GrantKeyCreated extends GrantKey {
  /**
   * The credential itself.
   *
   * ⚠ RETURNED ONCE, AT CREATION, AND NEVER AGAIN — the server's own words. A caller that does not
   * surface it here has lost it; `key_hint` is all that survives.
   */
  key?: string | null;
}

export interface GrantKeyRevoked {
  id: string;
  state: string;
}

export async function createAPIKey(payload: GrantKeyCreateRequest): Promise<GrantKeyCreated> {
  const response = await api.post<GrantKeyCreated>('/grants/keys', payload);
  return response.data;
}

/** Attach a resource to a key's bundle, with its own permissions (`POST /grants/keys/{id}/members`). */
export async function addAPIKeyMember(
  keyId: string,
  member: GrantCapabilities & { resource_id: string; role?: string | null },
): Promise<unknown> {
  const response = await api.post(`/grants/keys/${encodeURIComponent(keyId)}/members`, member);
  return response.data;
}

/**
 * A key over the collections a view names, at one access level: `viewer` (read only), `editor`
 * (read and write) or `collaborator` (also invoke operations, as a timer running a workflow needs). One collection is a plain key on it; several are a bundle with one member
 * each, so the key reaches those and nothing else. A key that names nothing is refused: a bundle
 * with no members would be a credential that reaches nothing and looks like one that works.
 */
export async function createKeyOver(
  name: string,
  role: 'viewer' | 'editor' | 'collaborator',
  resources: string[],
  expiresAt?: string | null,
  now: number = Date.now(),
): Promise<GrantKeyCreated> {
  // Minted at Origin's own page, in the person's Origin session (John, 2026-11-14). The page shows
  // the token once, there; this app gets the key's id and never the token.
  const ids = resources.map((r) => r.trim()).filter(Boolean);
  if (!ids.length) throw new Error('A key must name at least one collection it reaches');
  const until = expiresAt ? Date.parse(expiresAt) : NaN;
  const days = Number.isFinite(until)
    ? Math.max(1, Math.min(KEY_MAX_DAYS, Math.ceil((until - now) / 86400000)))
    : 30;
  const actions = ROLE_ACTIONS[role].join('+');
  const id = await askOrigin(
    { name, members: ids.map((r) => `${r}:${actions}`).join(','), days: String(days) },
    (data) => (data.type === 'agience.key' && typeof data.grant_id === 'string' && data.grant_id
      ? data.grant_id : undefined),
    '/key',
  );
  return { id, name, state: 'active', created_time: new Date(now).toISOString(),
           expires_at: new Date(now + days * 86400000).toISOString() };
}

export async function listAPIKeys(): Promise<GrantKey[]> {
  const response = await api.get<GrantKey[]>('/grants/keys');
  return response.data;
}

export async function getAPIKey(keyId: string): Promise<GrantKey> {
  const response = await api.get<GrantKey>(`/grants/keys/${encodeURIComponent(keyId)}`);
  return response.data;
}

/** Revoke a key at Origin's own page. The record survives in `state: revoked`; the credential
 *  stops working. */
export async function deleteAPIKey(keyId: string): Promise<GrantKeyRevoked> {
  await askOrigin(
    { revoke: keyId },
    (data) => (data.type === 'agience.key-revoked' && data.grant_id === keyId ? true : undefined),
    '/key',
  );
  return { id: keyId, state: 'revoked' };
}

/** A key's expiry as a view asked for it: an ISO time in the future and within `KEY_MAX_DAYS`
 *  (FR-019), or null when it is absent, unparseable, past, or further out. */
export function keyExpiry(value: unknown, now: number = Date.now()): string | null {
  if (typeof value !== 'string' || !value) return null;
  const t = Date.parse(value);
  if (!Number.isFinite(t) || t <= now || t > now + KEY_MAX_DAYS * 86400000) return null;
  return new Date(t).toISOString();
}
