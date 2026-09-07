// api/workspaces.ts

import { get, getList, post, postList, patch, del } from './api';
import { WORKSPACE_CONTENT_TYPE } from '@/utils/content-type';
import { subscribeEvents, type BusEvent } from './events';
import {
  WorkspaceResponse,
  WorkspaceCreate,
  WorkspaceUpdate,
} from './types/workspace';
import { ArtifactResponse, ArtifactCreate, ArtifactUpdate } from './types/artifact';
import {
  type WorkspaceCommitRequest,
  type WorkspaceCommitResponse,
} from './types/workspace_commit';
import type { ArtifactKeyResponse } from './types/workspace_card';

// list all workspaces accessible to the caller
export function listWorkspaces(): Promise<WorkspaceResponse[]> {
  return getList('/artifacts/visible?content_type=' + encodeURIComponent('application/vnd.agience.workspace+json'));
}

// get one workspace
export function getWorkspace(id: string): Promise<WorkspaceResponse> {
  return get(`/artifacts/${id}`);
}

// create new workspace
export function createWorkspace(
  input: WorkspaceCreate
): Promise<WorkspaceResponse> {
  return post('/artifacts', { ...input, content_type: WORKSPACE_CONTENT_TYPE });
}

// update name/description
export function updateWorkspace(
  id: string,
  input: WorkspaceUpdate
): Promise<WorkspaceResponse> {
  return patch(`/artifacts/${id}`, input);
}

// delete workspace
export function deleteWorkspace(id: string): Promise<void> {
  return del(`/artifacts/${id}`);
}

// list artifacts in workspace
export async function listWorkspaceArtifacts(
  workspaceId: string
): Promise<{ items: ArtifactResponse[]; order_version?: number }> {
  const res = await get(`/artifacts/${encodeURIComponent(workspaceId)}/children`) as ArtifactResponse[] | { items: ArtifactResponse[]; order_version?: number };
  return Array.isArray(res) ? { items: res } : res;
}

// add an artifact
export function addArtifactToWorkspace(
  workspaceId: string,
  input: ArtifactCreate
): Promise<ArtifactResponse> {
  return post('/artifacts', { container_id: workspaceId, ...input });
}

// Import a collection artifact (by root_id) into a workspace — links, does not copy
export function importCollectionArtifactToWorkspace(
  workspaceId: string,
  rootId: string
): Promise<ArtifactResponse> {
  return post(`/artifacts`, { container_id: workspaceId, source_artifact_id: rootId });
}

// update an artifact
export function updateWorkspaceArtifact(
  _workspaceId: string,
  artifactId: string,
  input: ArtifactUpdate
): Promise<ArtifactResponse> {
  return patch(`/artifacts/${artifactId}`, input);
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
): Promise<void> {
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
  return postList<ArtifactResponse>('/artifacts/batch', { artifact_ids: artifactIds });
}

export async function revertWorkspaceArtifact(
  _workspaceId: string,
  artifactId: string
): Promise<ArtifactResponse> {
  return post(`/artifacts/${artifactId}/revert`, {});
}

// move artifact between workspaces
export async function moveArtifactToWorkspace(
  _sourceWorkspaceId: string,
  artifactId: string,
  targetWorkspaceId: string
): Promise<ArtifactResponse> {
  return post(`/artifacts/${artifactId}/op/move`, { target_container_id: targetWorkspaceId });
}

// Commit drafts to their collections. Pass `artifact_ids` to commit a subset
// (per-card or multi-select); omit to commit every draft in the workspace.
// Commit is a type operation dispatched via the generic op endpoint.
export async function commitWorkspace(
  workspaceId: string,
  input?: WorkspaceCommitRequest
): Promise<WorkspaceCommitResponse> {
  return post(`/artifacts/${workspaceId}/op/commit`, input);
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

export async function orderWorkspaceArtifacts(
  workspaceId: string,
  orderedIds: string[],
  version?: number
): Promise<{ ok: boolean; version: number }> {
  const result = await patch<{ order_version: number }>(`/artifacts/${workspaceId}/children/order`, {
    ordered_ids: orderedIds,
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

// Get presigned URL for a specific part in multipart upload
export function getMultipartPartUrl(
  _workspaceId: string,
  uploadId: string,
  partNumber: number
): Promise<{ url: string; part_number: number }> {
  return get(`/artifacts/${uploadId}/multipart-part-url?part_number=${partNumber}`);
}

// Get signed content URL for an artifact's file
export function getArtifactContentUrl(
  _workspaceId: string,
  artifactId: string,
): Promise<{ url: string; expires_in: number | null; filename?: string }> {
  return get(`/artifacts/${artifactId}/content-url`);
}

// Artifact-scoped key rotation
/** Generate or rotate an artifact-scoped API key. Shown once — save immediately. */
export function rotateArtifactKey(
  _workspaceId: string,
  artifactId: string,
  keyContext: string,
): Promise<ArtifactKeyResponse> {
  return post(`/artifacts/${artifactId}/key?key_context=${encodeURIComponent(keyContext)}`, {});
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
        case 'upload.complete': {
          const a = (payload as { artifact?: ArtifactResponse }).artifact;
          if (a) {
            handlers.onUploadComplete?.(a);
            handlers.onArtifactUpdated?.(a);
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
