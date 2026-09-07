// api/secrets.ts
import api, { getList } from './api';

/**
 * Secrets API — artifact-backed (BYOK).
 *
 * A secret is an ordinary artifact the user owns: the value is the artifact's CONTENT, which the
 * write boundary encrypts at rest, and the light cone decides who may read it. There is no second
 * store and no second authorization path.
 *
 * ⛔ CORRECTED 2026-08-25 ON BOTH COUNTS. This module used to call `/secrets/artifact`, and Mantle
 * has no `/secrets/*` route at all — no `secrets_router.py`, nothing — so `listSecrets` and
 * `addSecret` were 404ing while `deleteSecret` beside them already used `/artifacts/{id}`. A
 * migration that was started and left half-done reads exactly like a working one.
 *
 * ⚠ And the content type above was `application/vnd.agience.secret+json`, which is defined
 * NOWHERE in the workspace. Mantle defines and produces `application/vnd.agience.credential+json`
 * (`services/bootstrap_types.py`, written by `seed_provisioning/platform_email.py`). Two names for
 * one concept, and this file held the one with no implementation behind it.
 */

/** The content type Mantle actually defines and writes for a credential. */
const CREDENTIAL_CONTENT_TYPE = 'application/vnd.agience.credential+json';

/** An artifact document as the read path returns it. `context` is plaintext metadata. */
interface CredentialArtifact {
  id: string;
  created_time?: string;
  context?: string | Record<string, unknown>;
}

/**
 * The plaintext metadata off a credential artifact. `context` travels as a JSON string, but the
 * read path may hand back either form. A context that will not parse yields `{}` — a credential
 * that cannot be classified must not match a filter and be shown as something it is not.
 */
function credentialContext(doc: CredentialArtifact): Record<string, unknown> {
  const raw = doc.context;
  if (raw && typeof raw === 'object') return raw as Record<string, unknown>;
  if (typeof raw !== 'string') return {};
  try {
    const parsed: unknown = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

export interface SecretResponse {
  id: string;
  type: string;
  provider: string;
  label: string;
  created_time: string;
  is_default: boolean;
}

export interface SecretCreateRequest {
  type: string;
  provider: string;
  label: string;
  value: string;
  is_default?: boolean;
}

/**
 * List the caller's secret artifacts (metadata only), optionally filtered by type/provider.
 */
export async function listSecrets(
  type?: string,
  provider?: string
): Promise<SecretResponse[]> {
  // ⚠ Narrowed HERE, not by Mantle. `/artifacts/visible` filters only on `content_type`, and
  // `/artifacts/recall` refuses a query made of nothing but filters by design. The set is one
  // user's credentials, so it is small.
  const rows = await getList<CredentialArtifact>('/artifacts/visible', {
    params: { content_type: CREDENTIAL_CONTENT_TYPE, limit: 1000 },
  });
  return rows
    .map((doc) => ({ doc, ctx: credentialContext(doc) }))
    .filter(({ ctx }) => (!type || ctx.kind === type) && (!provider || ctx.provider === provider))
    .map(({ doc, ctx }) => ({
      id: doc.id,
      type: String(ctx.kind ?? ''),
      provider: String(ctx.provider ?? ''),
      label: String(ctx.label ?? ''),
      created_time: doc.created_time ?? '',
      is_default: false, // artifact secrets have no "default" flag; resolution is by (provider, type)
    }));
}

/**
 * Store a new secret as an owned artifact (material encrypted server-side). Returns the list.
 */
export async function addSecret(
  request: SecretCreateRequest
): Promise<SecretResponse[]> {
  await api.post('/artifacts', {
    content_type: CREDENTIAL_CONTENT_TYPE,
    // The value is the artifact's content and nothing else holds it — that is what puts it under
    // the envelope. `context` is plaintext, so it carries only the non-secret metadata.
    content: JSON.stringify({ value: request.value }),
    context: JSON.stringify({
      content_type: CREDENTIAL_CONTENT_TYPE,
      kind: request.type,
      provider: request.provider,
      label: request.label,
    }),
    name: request.label,
  });
  return listSecrets(request.type);
}

/**
 * Delete a secret artifact (removes the artifact; material is orphaned in the vault). Returns the list.
 */
export async function deleteSecret(secretId: string): Promise<SecretResponse[]> {
  await api.delete(`/artifacts/${secretId}`);
  return listSecrets();
}

/**
 * No-op for artifact-backed secrets: there is no per-(type,provider) "default" — a service
 * resolves by provider/type directly. Kept so the existing UI's set-default control is harmless.
 */
export async function setDefaultSecret(
  _secretId: string
): Promise<SecretResponse[]> {
  return listSecrets();
}
