// Dropping artifacts on an artifact: Crystal keeps those its type accepts and runs the op the
// type declares with them.
import { post } from './api';

export interface DropResult {
  accepted: string[];
  refused: string[];
  accepts?: string[];
  result?: unknown;
}

/** Drops `ids` on `artifactId`; answers what was accepted and refused. */
export function dropOn(artifactId: string, ids: string[], workspaceId?: string): Promise<DropResult> {
  return post<DropResult>(`/artifacts/${encodeURIComponent(artifactId)}/op/drop`, {
    ids,
    ...(workspaceId ? { workspace_id: workspaceId } : {}),
  });
}
