// api/workspaces.ts

import type { RemoveResult } from '../utils/removal';
import { get, getList, LIST_PAGE, post, postList, patch, del } from './api';
import { WORKSPACE_CONTENT_TYPE } from '@/utils/content-type';
import { subscribeEvents, type BusEvent } from './events';
import { completeFromFeed } from './feedArtifact';
import { withMarks } from './marks';
import { namedCreate, updateArtifact } from './artifacts';
import {
  WorkspaceResponse,
  WorkspaceCreate,
  WorkspaceUpdate,
} from './types/workspace';
import { ArtifactResponse, ArtifactCreate, ArtifactUpdate } from './types/artifact';
import { stringifyArtifactContext } from '@/utils/artifactContext';

// list all workspaces accessible to the caller, oldest first. Crystal marks what the workspace
// type keeps (`inbox`, each person's first workspace) and takes the ops it refuses out of
// `allowed_actions`. Each `name` is the title Mantle shows it by.
export async function listWorkspaces(): Promise<WorkspaceResponse[]> {
  return withMarks(
    getList<WorkspaceResponse>('/types/visible?content_type=' + encodeURIComponent('application/vnd.agience.workspace+json')),
    WORKSPACE_CONTENT_TYPE);
}

// get one workspace
export async function getWorkspace(id: string): Promise<WorkspaceResponse> {
  return get<WorkspaceResponse>(`/artifacts/${id}`);
}

// create new workspace
export async function createWorkspace(
  input: WorkspaceCreate
): Promise<WorkspaceResponse> {
  // The title is content and lives in the context. A blank name is sent blank: Crystal names it.
  const title = input.name.trim();
  return namedCreate<WorkspaceResponse>({
    ...input, name: title, content_type: WORKSPACE_CONTENT_TYPE,
    context: stringifyArtifactContext({ content_type: WORKSPACE_CONTENT_TYPE, ...(title ? { title } : {}) }),
  });
}

// update name/description (and, with them, the context that holds the title)
export async function updateWorkspace(
  id: string,
  input: WorkspaceUpdate
): Promise<WorkspaceResponse> {
  return updateArtifact<WorkspaceResponse>(id, input);
}

// list artifacts in workspace
export async function listWorkspaceArtifacts(
  workspaceId: string
): Promise<{ items: ArtifactResponse[]; order_version?: number }> {
  const url = `/artifacts/${encodeURIComponent(workspaceId)}/children`;
  const res = await get(url, { params: { limit: LIST_PAGE } }) as ArtifactResponse[]
    | { items: ArtifactResponse[]; order_version?: number; has_more?: boolean };
  if (Array.isArray(res)) return { items: res };
  if (!res.has_more) return res;
  // Past one page (2026-11-13: lists stopped at the first 100): the rest, followed and kept once by
  // id, after the first page that carries `order_version`.
  const rest = await getList<ArtifactResponse>(url, { params: { offset: res.items.length } });
  const seen = new Set(res.items.map((a) => a.id));
  return { ...res, items: [...res.items, ...rest.filter((a) => !seen.has(a.id))] };
}

// add an artifact
export function addArtifactToWorkspace(
  workspaceId: string,
  input: ArtifactCreate
): Promise<ArtifactResponse> {
  return namedCreate({ container_id: workspaceId, ...input });
}

// Import a collection artifact (by root_id) into a workspace — links, does not copy
export function importCollectionArtifactToWorkspace(
  workspaceId: string,
  rootId: string,
  beforeId?: string
): Promise<ArtifactResponse> {
  return post(`/artifacts`, {
    container_id: workspaceId,
    source_artifact_id: rootId,
    ...(beforeId ? { before_id: beforeId } : {}),
  });
}

// update an artifact
export function updateWorkspaceArtifact(
  _workspaceId: string,
  artifactId: string,
  input: ArtifactUpdate
): Promise<ArtifactResponse> {
  return updateArtifact(artifactId, input);
}

// delete an artifact
export function deleteWorkspaceArtifact(
  _workspaceId: string,
  artifactId: string
): Promise<void> {
  return del(`/artifacts/${artifactId}`);
}

export function removeWorkspaceArtifact(
  workspaceId: string,
  artifactId: string,
): Promise<RemoveResult> {
  // ⛑ `DELETE /artifacts/{container_id}/children/{artifact_id}` since 2026-08-26 (audit
  // M2 + M4). It was `POST /artifacts/{artifact_id}/remove` with the container in the BODY --
  // the inverse of every other two-id operation, and the reason the verb could not simply
  // change: `DELETE` with a request body has no defined semantics in HTTP and
  // intermediaries may drop it. Moving the container into the PATH is what makes the
  // bodyless `DELETE` possible, so the two moved together.
  return del(`/artifacts/${encodeURIComponent(workspaceId)}/children/${encodeURIComponent(artifactId)}`);
}

// batch fetch artifacts across all accessible workspaces
export async function getWorkspaceArtifactsBatchGlobal(
  artifactIds: string[]
): Promise<ArtifactResponse[]> {
  // ⛑ `postList`, not a raw `post` reading `res.artifacts`. That key was retired when
  // `/artifacts/batch` moved to the one page shape, so the read returned `undefined` and
  // `?? []` turned it into an empty list — this search found nothing and said nothing.
  // `include_archived`: these are ids a search returned, and a search of the archived segment
  // returns archived ones.
  return postList<ArtifactResponse>('/artifacts/batch', { artifact_ids: artifactIds, include_archived: true });
}

// move artifact between workspaces
export async function moveArtifactToWorkspace(
  _sourceWorkspaceId: string,
  artifactId: string,
  targetWorkspaceId: string
): Promise<ArtifactResponse> {
  return post(`/artifacts/${artifactId}/op/move`, { target_container_id: targetWorkspaceId });
}

// find artifacts similar to a freeform text input
export function findSimilarText(
  input: string
): Promise<ArtifactResponse[]> {
  return post('/artifacts/recall', { query_text: input });
}

// find artifacts similar to a given artifact in the same workspace
export function findSimilarArtifact(
  artifactId: string
): Promise<ArtifactResponse[]> {
  // Passes the artifact's ID as the query text to the shared recall endpoint.
  return post('/artifacts/recall', { query_text: artifactId });
}

/** Mantle moves `ids`, in that order, to sit just before `beforeId` (last when it is null). */
export async function moveWorkspaceArtifacts(
  workspaceId: string,
  ids: string[],
  beforeId: string | null,
  version?: number
): Promise<{ ok: boolean; version: number }> {
  const result = await patch<{ order_version: number }>(`/artifacts/${workspaceId}/children/order`, {
    move_ids: ids,
    ...(beforeId ? { before_id: beforeId } : {}),
    ...(version !== undefined ? { order_version: version } : {}),
  });
  return { ok: true, version: result.order_version };
}

// Upload operations
import type {
  UploadInitiateRequest,
  UploadInitiateResponse,
  UploadStatusUpdateRequest,
} from './types/upload';

export function initiateUpload(
  workspaceId: string,
  input: UploadInitiateRequest
): Promise<UploadInitiateResponse> {
  return post(`/artifacts/${workspaceId}/upload-initiate`, input);
}

export function updateUploadStatus(
  _workspaceId: string,
  uploadId: string,
  input: UploadStatusUpdateRequest
): Promise<ArtifactResponse> {
  return patch(`/artifacts/${uploadId}/upload-status`, input);
}


// Get signed content URL for an artifact's file
export function getArtifactContentUrl(
  _workspaceId: string,
  artifactId: string,
): Promise<{ url: string; expires_in: number | null; filename?: string }> {
  return get(`/artifacts/${artifactId}/content-url`);
}


// === Workspace Change Events (SSE) ===

export type InvokeEventPayload = {
  artifact_id?: string;
  container_id?: string;
  content_type?: string;
  op?: string;
  phase?: string;
  actor_id?: string;
  ts?: number;
  result?: unknown;
  error?: { type: string; message: string };
};

export type WorkspaceEventHandlers = {
  onArtifactCreated?: (artifact: ArtifactResponse) => void;
  onArtifactUpdated?: (artifact: ArtifactResponse) => void;
  onArtifactDeleted?: (artifactId: string) => void;
  onUploadComplete?: (artifact: ArtifactResponse) => void;
  onWorkspaceRefreshed?: () => void;
  // Operation lifecycle events, fired by the operation dispatcher's emit envelope around every invoke.
  onInvokeStarted?: (payload: InvokeEventPayload) => void;
  onInvokeCompleted?: (payload: InvokeEventPayload) => void;
  onInvokeFailed?: (payload: InvokeEventPayload) => void;
};

/**
 * Call `onChange` with an item's id each time a grant on it is applied at Mantle. Mantle delivers
 * the event only where the item can now be read, so a claimed invitation reaches the person it
 * was for. Returns the cleanup function.
 */
export function subscribeAccessChanges(onChange: (artifactId: string) => void): () => void {
  return subscribeEvents({ event_names: ['access.changed'] }, (evt: BusEvent) => {
    const id = (evt.payload as { artifact_id?: string } | undefined)?.artifact_id;
    if (id) onChange(id);
  });
}

/**
 * Subscribe to real-time workspace change events via the unified /events
 * WebSocket. Thin adapter over `subscribeEvents` in api/events.ts that
 * translates `BusEvent` messages into a per-event handler-callback shape.
 *
 * Returns a cleanup function — call it to tear down the subscription (use
 * as a useEffect return value).
 */
export function subscribeWorkspaceEvents(
  workspaceId: string,
  handlers: WorkspaceEventHandlers,
): () => void {
  return subscribeEvents(
    {
      container_id: workspaceId,
      event_names: [
        'artifact.created',
        'artifact.updated',
        'artifact.deleted',
        'upload.complete',
        'workspace.refreshed',
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
        case 'upload.complete': {
          const a = (payload as { artifact?: ArtifactResponse }).artifact;
          if (a) {
            void completeFromFeed(a).then((full) => {
              handlers.onUploadComplete?.(full);
              handlers.onArtifactUpdated?.(full);
            });
          }
          return;
        }
        case 'workspace.refreshed':
          handlers.onWorkspaceRefreshed?.();
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
