// api/collections.ts

import { get, getList, post, postList, patch, del } from './api';
import { COLLECTION_CONTENT_TYPE } from '@/utils/content-type';
import { subscribeEvents, type BusEvent } from './events';
import {
  CollectionResponse,
  CollectionCommitResponse,
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
export function listCollections(action: string = 'read'): Promise<CollectionResponse[]> {
  let url = '/artifacts/visible?content_type=' + encodeURIComponent('application/vnd.agience.collection+json');
  if (action !== 'read') {
    url += '&action=' + encodeURIComponent(action);
  }
  return getList(url);
}

// get a single collection
export function getCollection(id: string, _grantKey?: string): Promise<CollectionResponse> {
  return get(`/artifacts/${id}`);
}

export function listCollectionCommits(collectionId: string): Promise<CollectionCommitResponse[]> {
  return get(`/artifacts/${collectionId}/commits`);
}

// create a new collection
export function createCollection(
  input: CollectionCreate,
  containerId?: string,
): Promise<CollectionResponse> {
  // A collection is an artifact — created in a container (the active workspace),
  // it becomes a member and shows there like anything else. Omit container for
  // a top-level collection.
  return post('/artifacts', {
    ...input,
    content_type: COLLECTION_CONTENT_TYPE,
    ...(containerId ? { container_id: containerId } : {}),
  });
}

// update name/description
export function updateCollection(
  id: string,
  input: CollectionUpdate
): Promise<CollectionResponse> {
  return patch(`/artifacts/${id}`, input);
}

// delete collection
export function deleteCollection(id: string): Promise<void> {
  return del(`/artifacts/${id}`);
}

// grants, via the /grants endpoints
export function listGrants(collectionId: string): Promise<GrantResponse[]> {
  return get(`/grants?resource_id=${encodeURIComponent(collectionId)}`);
}

export function createGrant(
  collectionId: string,
  input: Omit<GrantCreate, 'resource_id'>
): Promise<GrantResponse> {
  return post('/grants', { resource_id: collectionId, ...input });
}

export function updateGrant(
  grantId: string,
  input: GrantUpdate
): Promise<GrantResponse> {
  return patch(`/grants/${grantId}`, input);
}

export function deleteGrant(grantId: string): Promise<void> {
  return del(`/grants/${grantId}`);
}

export function getGrant(grantId: string): Promise<GrantResponse> {
  return get(`/grants/${grantId}`);
}

// artifacts
export function listCollectionArtifacts(collectionId: string, workspaceId?: string): Promise<ArtifactResponse[]> {
  // Passing the caller's active workspace surfaces this workspace's drafts that
  // are linked into the collection (drafts are workspace-private; the server gates
  // it on the caller's read access to that workspace). Omit for committed-only.
  const q = workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : '';
  return getList<ArtifactResponse>(`/artifacts/${encodeURIComponent(collectionId)}/children${q}`);
}

export const getCollectionArtifacts = listCollectionArtifacts;

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

export function removeArtifactFromCollection(collectionId: string, rootId: string): Promise<void> {
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
  return postList<ArtifactResponse>('/artifacts/batch', { artifact_ids: rootIds });
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
          if (a) handlers.onArtifactCreated?.(a);
          return;
        }
        case 'artifact.updated': {
          const a = (payload as { artifact?: ArtifactResponse }).artifact;
          if (a) handlers.onArtifactUpdated?.(a);
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
