// api/history.ts — what the store recorded about a card: its earlier versions, and who reached it.

import { get, post } from './api';
import type { ArtifactResponse } from './types/artifact';

/** One access decision the store witnessed (`mantle/db/audit.py`). `ctx.via` is how the caller
 *  authenticated (a person, a grant key, an MCP client); `ctx.actor` the persona or client that
 *  acted for a person, when one did. */
export interface AccessEvent {
  principal_id: string;
  action: string;
  result: 'allowed' | 'denied' | string;
  ts: string;
  ctx?: { via?: string; actor?: string | null; grant_key_id?: string | null; reason?: string } & Record<string, unknown>;
}

export interface AccessLogPage {
  artifact_id: string;
  items: AccessEvent[];
  total: number | null;
  has_more: boolean;
}

/** Newest first. Needs `admin` on the card; anyone else gets 404 or 403 (no existence oracle). */
export function getAccessLog(artifactId: string, limit = 100): Promise<AccessLogPage> {
  return get(`/artifacts/${encodeURIComponent(artifactId)}/access-log?limit=${limit}`);
}


/** One version on a card's line (`GET /artifacts/{id}/versions`): the current one, then each one it
 *  was made from. Only versions the caller can read are listed. */
export interface VersionSummary {
  id: string;
  parent_id: string | null;
  current: boolean;
  title: string | null;
  modified_time: string | null;
  modified_by: string | null;
}

export interface VersionsPage {
  artifact_id: string;
  items: VersionSummary[];
  total: number | null;
  has_more: boolean;
}

export function listVersions(artifactId: string): Promise<VersionsPage> {
  return get(`/artifacts/${encodeURIComponent(artifactId)}/versions`);
}

/** One version as it was: its content and title. */
export function getVersion(artifactId: string, versionId: string): Promise<ArtifactResponse> {
  return get(`/artifacts/${encodeURIComponent(artifactId)}/versions/${encodeURIComponent(versionId)}`);
}

/** Write a version's content and title as the card's current ones: a new version, nothing lost. */
export function restoreVersion(artifactId: string, versionId: string): Promise<ArtifactResponse> {
  return post(`/artifacts/${encodeURIComponent(artifactId)}/versions/${encodeURIComponent(versionId)}/restore`, {});
}
