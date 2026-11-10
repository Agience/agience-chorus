// api/collections.ts

import { get, getList, post, postList, patch, del } from './api';
import {
  changeGrant, listGrantsAtOrigin, makeGrant, revokeGrant, type GrantInput,
} from './authority';
import type { RemoveResult } from '../utils/removal';
import { COLLECTION_CONTENT_TYPE } from '@/utils/content-type';
import { subscribeEvents, type BusEvent } from './events';
import { completeFromFeed } from './feedArtifact';
import { titled } from '@/utils/untitled';
import { safeParseArtifactContext, stringifyArtifactContext } from '@/utils/artifactContext';
import {
  CollectionResponse,
  CollectionCreate,
  CollectionUpdate,
  GrantResponse,
  GrantCreate,
  GrantUpdate,
  ArtifactResponse,
} from './types';

// list collections accessible to the caller.
//
// `action` selects the CRUDEASIO capability to filter by:
//   - 'read'   (default) — every collection the caller can see (browse/sidebar)
//   - 'create' — only collections the caller can assign artifacts into; this
//     excludes read-only platform collections (which are never assignable to
//     regular users — only the platform admin holds create/add on them).
// ⚠ THE PATH IS SPELLED AT THE CALL, NOT ASSEMBLED INTO A VARIABLE FIRST. It used to be built
// across four lines and passed as `getList(url)`, which reads fine and is invisible to the check
// that asks whether every endpoint this app calls exists: `deploy/facet_contract_drift.py` can
// only follow a literal, so this one call site was reported as unverifiable on every run — the
// single blind spot in a gate that otherwise covers the whole api layer. A path a tool cannot read
// is a path nobody is checking.
export async function listCollections(action: string = 'read'): Promise<CollectionResponse[]> {
  // `encodeURIComponent`, not `URLSearchParams`: the latter is form-encoding and would be a
  // different encoder over the same values. This keeps the bytes on the wire identical.
  const scope = action === 'read' ? '' : `&action=${encodeURIComponent(action)}`;
  // Each is `titled`: its `name` is the title it is shown by.
  const list = await getList<CollectionResponse>(
    `/artifacts/visible?content_type=${encodeURIComponent(COLLECTION_CONTENT_TYPE)}${scope}`,
  );
  return list.map(titled);
}

// Every artifact of one content type the caller can read: what a picker offers for an argument
// that names an artifact of that type.
export function listVisibleOfType(contentType: string): Promise<ArtifactResponse[]> {
  return getList('/artifacts/visible', { params: { content_type: contentType } });
}

// get a single collection
export async function getCollection(id: string, _grantKey?: string): Promise<CollectionResponse> {
  return titled(await get<CollectionResponse>(`/artifacts/${id}`));
}


// create a new collection
export async function createCollection(
  input: CollectionCreate,
  containerId?: string,
): Promise<CollectionResponse> {
  // A collection is an artifact — created in a container (the active workspace),
  // it becomes a member and shows there like anything else. Omit container for
  // a top-level collection.
  // The title is content and lives in the context; `name` is kept beside it for older readers.
  return titled(await post<CollectionResponse>('/artifacts', {
    ...input,
    content_type: COLLECTION_CONTENT_TYPE,
    context: stringifyArtifactContext({ content_type: COLLECTION_CONTENT_TYPE, title: input.name }),
    ...(containerId ? { container_id: containerId } : {}),
  }));
}

// update name/description
export async function updateCollection(
  id: string,
  input: CollectionUpdate
): Promise<CollectionResponse> {
  // A rename sets the context's title too, which is what cards and pickers show. The whole client
  // context is sent: an update replaces the client's keys, so it is read first.
  if (input.name === undefined) return titled(await patch<CollectionResponse>(`/artifacts/${id}`, input));
  const current = await get<CollectionResponse>(`/artifacts/${id}`);
  const context = stringifyArtifactContext({ ...safeParseArtifactContext(current.context), title: input.name });
  return titled(await patch<CollectionResponse>(`/artifacts/${id}`, { ...input, context }));
}

// delete collection
export function deleteCollection(id: string): Promise<void> {
  return del(`/artifacts/${id}`);
}

// The grants on a resource, as Origin's own record holds them, read in the person's Origin session
// (round 13). Mantle's listing is never the source of a change.
export function listGrants(collectionId: string): Promise<GrantResponse[]> {
  return listGrantsAtOrigin(collectionId);
}

// A grant, an invite, a change or a revocation is made at Origin, in the person's Origin session
// (review 12): the token Mantle holds changes no authority. Mantle lists them once it has applied
// Origin's entries from the feed.
export function createGrant(
  collectionId: string,
  input: Omit<GrantCreate, 'resource_id'>
): Promise<GrantResponse> {
  return makeGrant(collectionId, input as GrantInput);
}

export function updateGrant(
  grant: GrantResponse,
  input: GrantUpdate
): Promise<GrantResponse> {
  return changeGrant(grant, input as GrantInput & { state?: string });
}

export function deleteGrant(grant: GrantResponse): Promise<void> {
  return revokeGrant(grant);
}



export function getGrant(grantId: string): Promise<GrantResponse> {
  return get(`/grants/${grantId}`);
}

// artifacts
export function listCollectionArtifacts(collectionId: string): Promise<ArtifactResponse[]> {
  return getList<ArtifactResponse>(`/artifacts/${encodeURIComponent(collectionId)}/children`);
}

export const getCollectionArtifacts = listCollectionArtifacts;

/** A container's archived members, homed there or linked in. Default listings read past them;
 * this is how they are found and restored. Works for workspaces and collections alike. */
export function listArchivedChildren(containerId: string): Promise<ArtifactResponse[]> {
  return getList<ArtifactResponse>(`/artifacts/${encodeURIComponent(containerId)}/children?state=archived`);
}

export function getCollectionArtifact(_collectionId: string, rootId: string, _grantKey?: string): Promise<ArtifactResponse> {
  return get(`/artifacts/${rootId}`);
}

export function getCollectionArtifactContentUrl(
  _collectionId: string,
  rootId: string,
  _grantKey?: string,
): Promise<{ url: string; expires_in: number | null; filename?: string }> {
  return get(`/artifacts/${rootId}/content-url`);
}

export function addArtifactToCollection(_collectionId: string, versionId: string): Promise<ArtifactResponse> {
  return post(`/artifacts`, { container_id: _collectionId, source_artifact_id: versionId });
}

export function removeArtifactFromCollection(collectionId: string, rootId: string): Promise<RemoveResult> {
  // ⛑ `DELETE /artifacts/{container_id}/children/{artifact_id}` since 2026-08-26 (audit
  // M2 + M4). It was `POST /artifacts/{artifact_id}/remove` with the container in the BODY --
  // the inverse of every other two-id operation, and the reason the verb could not simply
  // change: `DELETE` with a request body has no defined semantics in HTTP and
  // intermediaries may drop it. Moving the container into the PATH is what makes the
  // bodyless `DELETE` possible, so the two moved together.
  return del(`/artifacts/${encodeURIComponent(collectionId)}/children/${encodeURIComponent(rootId)}`);
}

// batch fetch multiple artifacts across all accessible collections (global search)
export async function getCollectionArtifactsBatchGlobal(
  rootIds: string[]
): Promise<ArtifactResponse[]> {
  // ⛑ `postList`, not a raw `post` reading `res.artifacts`. That key was retired when
  // `/artifacts/batch` moved to the one page shape, so the read returned `undefined` and
  // `?? []` turned it into an empty list — this search found nothing and said nothing.
  // `include_archived`: these are ids a search returned, and a search of the archived segment
  // returns archived ones; without it the batch skipped them and the search showed nothing.
  return postList<ArtifactResponse>('/artifacts/batch', { artifact_ids: rootIds, include_archived: true });
}

// === Real-time collection events (WebSocket) ===

import type { InvokeEventPayload } from './workspaces';

export type CollectionEventHandlers = {
  onArtifactCreated?: (artifact: ArtifactResponse) => void;
  onArtifactUpdated?: (artifact: ArtifactResponse) => void;
  onArtifactDeleted?: (artifactId: string) => void;
  onCollectionRefreshed?: () => void;
  // Operation lifecycle events.
  onInvokeStarted?: (payload: InvokeEventPayload) => void;
  onInvokeCompleted?: (payload: InvokeEventPayload) => void;
  onInvokeFailed?: (payload: InvokeEventPayload) => void;
};

/**
 * Subscribe to real-time collection change events via the unified /events
 * WebSocket. Thin adapter over `subscribeEvents` in api/events.ts.
 */
export function subscribeCollectionEvents(
  collectionId: string,
  handlers: CollectionEventHandlers,
): () => void {
  return subscribeEvents(
    {
      container_id: collectionId,
      event_names: [
        'artifact.created',
        'artifact.updated',
        'artifact.deleted',
        'collection.refreshed',
        'artifact.invoke.started',
        'artifact.invoke.completed',
        'artifact.invoke.failed',
      ],
    },
    (evt: BusEvent) => {
      const payload = evt.payload || {};
      switch (evt.event) {
        case 'artifact.created': {
          const a = (payload as { artifact?: ArtifactResponse }).artifact;
          if (a) void completeFromFeed(a).then((full) => handlers.onArtifactCreated?.(full));
          return;
        }
        case 'artifact.updated': {
          const a = (payload as { artifact?: ArtifactResponse }).artifact;
          if (a) void completeFromFeed(a).then((full) => handlers.onArtifactUpdated?.(full));
          return;
        }
        case 'artifact.deleted': {
          const id = (payload as { artifact_id?: string }).artifact_id;
          if (id) handlers.onArtifactDeleted?.(id);
          return;
        }
        case 'collection.refreshed':
          handlers.onCollectionRefreshed?.();
          return;
        case 'artifact.invoke.started':
          handlers.onInvokeStarted?.(payload as unknown as InvokeEventPayload);
          return;
        case 'artifact.invoke.completed':
          handlers.onInvokeCompleted?.(payload as unknown as InvokeEventPayload);
          return;
        case 'artifact.invoke.failed':
          handlers.onInvokeFailed?.(payload as unknown as InvokeEventPayload);
          return;
      }
    },
  );
}

/**
 * Make `artifact` a member of exactly `nextIds` among the collections it is in now: added to each
 * new one, removed from each one left. Returns the memberships it holds afterwards, so a view can
 * show them at once rather than at its next refresh (BUG-021). Every change is tried; the first
 * failure is thrown after the rest have run, with what did change already in the returned list
 * of the error (`partial`).
 */
export async function setArtifactCollections(
  artifact: { id?: string | number; root_id?: string | null; committed_collection_ids?: string[] | null },
  nextIds: string[],
): Promise<string[]> {
  const current = (artifact.committed_collection_ids ?? []).map(String);
  const next = new Set(nextIds.map(String));
  const held = new Set(current);
  const rootId = String(artifact.root_id ?? artifact.id);
  let failure: unknown = null;
  for (const id of next) {
    if (held.has(id)) continue;
    try {
      await addArtifactToCollection(id, String(artifact.id));
      held.add(id);
    } catch (err) {
      failure ??= err;
    }
  }
  for (const id of current) {
    if (next.has(id)) continue;
    try {
      await removeArtifactFromCollection(id, rootId);
      held.delete(id);
    } catch (err) {
      failure ??= err;
    }
  }
  if (failure) {
    throw Object.assign(failure instanceof Error ? failure : new Error(String(failure)), { partial: [...held] });
  }
  return [...held];
}
