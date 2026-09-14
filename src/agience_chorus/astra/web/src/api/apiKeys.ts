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

export async function listAPIKeys(): Promise<GrantKey[]> {
  const response = await api.get<GrantKey[]>('/grants/keys');
  return response.data;
}

export async function getAPIKey(keyId: string): Promise<GrantKey> {
  const response = await api.get<GrantKey>(`/grants/keys/${encodeURIComponent(keyId)}`);
  return response.data;
}

/** Revoke a key. The record survives in `state: revoked`; the credential stops working. */
export async function deleteAPIKey(keyId: string): Promise<GrantKeyRevoked> {
  const response = await api.delete<GrantKeyRevoked>(`/grants/keys/${encodeURIComponent(keyId)}`);
  return response.data;
}
