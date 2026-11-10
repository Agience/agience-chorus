// api/artifacts.ts
//
// Unified artifact and grant API — calls the /artifacts and /grants endpoints, which
// apply uniformly across workspaces and collections rather than being scoped per container type.
//
// workspaces.ts and collections.ts call their own container-scoped routes; both sets of
// endpoints operate on the same underlying artifacts and grants.

import { get, getList, post, patch, del } from './api';
import { changeGrant, revokeGrant, type GrantInput } from './authority';
import type { ArtifactResponse } from './types/artifact';
import type { GrantResponse } from './types/grant';
import type { SearchResponse } from './types/search';
import type { InvokeResponse } from './types/invoke';

// ─────────────────────────────────────────────────────────────────────────────
// Artifact CRUD
// ─────────────────────────────────────────────────────────────────────────────

/** Create an artifact within a container (workspace or collection). */
export function createArtifact(
  containerId: string,
  context: string,
  content?: string,
): Promise<ArtifactResponse> {
  return post(`/artifacts`, { container_id: containerId, context, content });
}

/** Get a single artifact by ID. */
export function getArtifact(artifactId: string): Promise<ArtifactResponse> {
  return get(`/artifacts/${artifactId}`);
}

/** Update an artifact (partial patch). */
export function updateArtifact(
  artifactId: string,
  updates: Record<string, unknown>,
): Promise<ArtifactResponse> {
  return patch(`/artifacts/${artifactId}`, updates);
}

/** Delete an artifact for good. Delete as a person means it is {@link trashArtifact}. */
export function deleteArtifact(artifactId: string): Promise<void> {
  return del(`/artifacts/${artifactId}`);
}

/** Move an artifact to the caller's Trash: archived, and deleted for good after 30 days. */
export function trashArtifact(artifactId: string): Promise<ArtifactResponse> {
  return post(`/artifacts/${artifactId}/trash`);
}

/** Take an artifact out of Trash, back to the state it had: live, or archived if it was. */
export function untrashArtifact(artifactId: string): Promise<ArtifactResponse> {
  return post(`/artifacts/${artifactId}/untrash`);
}

/** The caller's Trash, most recently trashed first; each item carries `purge_after`. */
export function listTrash(): Promise<ArtifactResponse[]> {
  return getList(`/artifacts/trash`);
}

/** Fetch child artifacts of a parent artifact. */
export function getChildren(
  artifactId: string,
  params?: { content_type?: string; workspace_id?: string },
): Promise<ArtifactResponse[]> {
  return getList(`/artifacts/${artifactId}/children`, { params });
}

/**
 * Add an item to a container (workspace or collection).
 *
 * Analogous to createArtifact but semantically represents adding an existing
 * concept (e.g. importing a collection artifact into a workspace).
 */
export function addItemToContainer(
  containerId: string,
  context: string,
  content?: string,
): Promise<ArtifactResponse> {
  return post(`/artifacts`, { container_id: containerId, context, content });
}

/**
 * Invoke an artifact as an operator (Transform execution).
 *
 * Calls the unified invoke endpoint scoped to a specific artifact.
 */
/**
 * Invoke a workflow as the person, through Crystal, with the workflow as their session reads it
 * (`context`): the path a timer's firing takes, so its steps may reach any persona (BUG-044).
 */
export function invokeWithContext(
  artifactId: string,
  context: Record<string, unknown>,
  workspaceId?: string,
): Promise<unknown> {
  return post(`/artifacts/${artifactId}/op/invoke`, { context, workspace_id: workspaceId });
}

/**
 * A workflow's typed links, `{relationship: item id}`, as the person's own session lists them: a
 * persona's delegation cannot list a link to an item it cannot open, so the reach a run or a timer
 * asks for comes from here (BUG-051).
 */
export async function listLinks(artifactId: string): Promise<Record<string, string>> {
  const page = await get<{ items?: Array<Record<string, unknown>> } | Array<Record<string, unknown>>>(
    `/artifacts/${encodeURIComponent(artifactId)}/children`, { params: { links: '*', limit: 1000 } });
  const items = Array.isArray(page) ? page : (page?.items ?? []);
  const out: Record<string, string> = {};
  for (const m of items) {
    const rel = typeof m.relationship === 'string' ? m.relationship : '';
    const id = String(m.root_id ?? m.id ?? '');
    if (rel && id && !(rel in out)) out[rel] = id;
  }
  return out;
}

export function invokeArtifact(
  artifactId: string,
  input?: string,
  params?: Record<string, unknown>,
  workspaceId?: string,
  artifactIds?: string[],
): Promise<InvokeResponse> {
  return post(`/artifacts/${artifactId}/op/invoke`, {
    input,
    params,
    workspace_id: workspaceId,
    artifacts: artifactIds,
  });
}

/**
 * Recall artifacts across all accessible containers.
 *
 * ⚠ `contentTypes` IS ACCEPTED HERE AND NOT SENT, DELIBERATELY. `ArtifactRecallRequest` has no
 * `content_types` field — mantle's router names it among the three it stopped reading
 * (`artifacts_router.py:423`: "none is read on any path"). Sending it claimed a filter that was
 * not applied, which is worse than not offering one: a caller narrowing by type got every type
 * back and no error. The parameter stays on this signature because callers pass it and dropping
 * it would silently widen their results too; it is ignored, and says so.
 */
export function searchArtifacts(
  queryText: string,
  options?: {
    scope?: string[];
    contentTypes?: string[];
  },
): Promise<SearchResponse> {
  return post(`/artifacts/recall`, {
    query_text: queryText,
    scope: options?.scope,
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Grant management
// ─────────────────────────────────────────────────────────────────────────────

/** Get a single grant by ID. */
export function getGrant(grantId: string): Promise<GrantResponse> {
  return get(`/grants/${grantId}`);
}

/** Change a grant: restated at Origin, in the person's Origin session (review 12). */
export function updateGrant(
  grant: GrantResponse,
  updates: Record<string, unknown>,
): Promise<GrantResponse> {
  return changeGrant(grant, updates as GrantInput & { state?: string });
}

/** Revoke a grant at Origin. */
export function deleteGrant(grant: GrantResponse): Promise<void> {
  return revokeGrant(grant);
}

/** Claim an invite grant using its token. */
/** Claim an invite: at Origin, in the claimant's Origin session (review 12), never at Mantle. */
export async function claimInvite(token: string): Promise<GrantResponse> {
  const { claimInviteAtOrigin } = await import('./authority');
  return (await claimInviteAtOrigin(token)) as unknown as GrantResponse;
}

/** Accept a grant that requires explicit acceptance. */
export function acceptGrant(grantId: string): Promise<GrantResponse> {
  return post(`/grants/${grantId}/accept`, {});
}
