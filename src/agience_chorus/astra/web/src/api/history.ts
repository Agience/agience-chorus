// api/history.ts — what the store recorded about a card: who reached it, and how.

import { get } from './api';

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

/** One change to what a workspace or collection holds: the ids it added and removed. */
export interface ContainerCommit {
  id: string;
  message?: string | null;
  author_id?: string | null;
  created_time?: string | null;
  adds: string[];
  removes: string[];
}

export interface CommitPage {
  items: ContainerCommit[];
  total: number | null;
  has_more: boolean;
}

/** Newest first. Needs `read` on the card; a card that holds nothing has no commits. */
export function getCommits(artifactId: string, limit = 50): Promise<CommitPage> {
  return get(`/artifacts/${encodeURIComponent(artifactId)}/commits?limit=${limit}`);
}
