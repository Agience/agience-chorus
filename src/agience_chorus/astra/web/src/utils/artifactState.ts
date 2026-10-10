// utils/artifactState.ts
//
// An artifact's stored state is `live` or `archived`. Stores written before that rule still hold
// `committed` and `draft`, and a server mid-migration may still emit them; both mean `live`.
// Mantle's artifact responses pass through `normalizeArtifactStates` at the API boundary (the
// axios response interceptor in `api/api.ts`, for the endpoints `isArtifactEndpoint` names, and the
// event socket in `api/events.ts`), so nothing past it sees a legacy value. Other responses are
// left exactly as they arrived: an `/op/` call returns a tool's or MCP server's own payload, whose
// `state` fields mean whatever that server says they mean.

import type { ArtifactState } from '@/api/types/artifact';

const LEGACY_LIVE = new Set(['committed', 'draft']);

/** Map any state value an artifact may carry to `live` or `archived`. */
export function normalizeArtifactState(state: unknown): ArtifactState {
  return state === 'archived' ? 'archived' : 'live';
}

// Keys that mark an object as an artifact rather than some other record with a `state` field
// (a grant's `active`/`revoked`, a job's status).
const ARTIFACT_KEYS = ['context', 'content_type', 'root_id', 'collection_id'];

function isArtifactLike(obj: Record<string, unknown>): boolean {
  return ARTIFACT_KEYS.some((k) => k in obj);
}

// The Mantle endpoints whose responses are artifacts or pages of artifacts:
//   /artifacts                    create
//   /artifacts/visible            containers the caller can see
//   /artifacts/batch              fetch by id
//   /artifacts/recall             retrieval
//   /artifacts/search             retrieval
//   /artifacts/{id}               read, update
//   /artifacts/{id}/children      a container's members
//   /artifacts/{id}/upload-initiate  the new upload's artifact (`init.artifact`)
//   /artifacts/{id}/upload-status    the artifact once its upload completes
const ARTIFACT_ENDPOINTS = [
  /^\/artifacts\/?$/,
  /^\/artifacts\/(visible|batch|recall|search)\/?$/,
  /^\/artifacts\/[^/]+\/?$/,
  /^\/artifacts\/[^/]+\/children\/?$/,
  /^\/artifacts\/[^/]+\/upload-initiate\/?$/,
  /^\/artifacts\/[^/]+\/upload-status\/?$/,
];

/** True when a request URL (relative or absolute, with or without a query) is one of those. */
export function isArtifactEndpoint(url: string | undefined): boolean {
  if (!url) return false;
  let path: string;
  try {
    path = new URL(url, 'http://relative.invalid').pathname;
  } catch {
    return false;
  }
  return ARTIFACT_ENDPOINTS.some((re) => re.test(path));
}

/**
 * Rewrite legacy `committed`/`draft` states to `live`, in place, anywhere in a JSON payload.
 * Only artifact-shaped objects are touched, and only those two values; everything else is left
 * exactly as it arrived. Returns the payload for chaining.
 */
export function normalizeArtifactStates<T>(payload: T, depth = 0): T {
  if (depth > 8 || payload === null || typeof payload !== 'object') return payload;
  if (Array.isArray(payload)) {
    for (const item of payload) normalizeArtifactStates(item, depth + 1);
    return payload;
  }
  const obj = payload as Record<string, unknown>;
  if (typeof obj.state === 'string' && LEGACY_LIVE.has(obj.state) && isArtifactLike(obj)) {
    obj.state = 'live';
  }
  for (const value of Object.values(obj)) {
    if (value !== null && typeof value === 'object') normalizeArtifactStates(value, depth + 1);
  }
  return payload;
}
