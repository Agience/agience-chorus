// api/contentTypes.ts
//
// Runtime content-type discovery. The platform (Mantle) is the single source of
// resolved type definitions — it aggregates core (package/types) + every server's
// own types and serves them merged (core < server overrides). Facet fetches them
// at runtime and hydrates its registry; it never compiles server types in.

import { get } from './api';

/** One resolved type definition as served by Mantle's GET /types/all. */
export interface ServerTypeEntry {
  content_type: string;
  /** Merged type definition (carries the nested `ui` block). Opaque to transport. */
  definition: Record<string, unknown>;
  validation_errors?: string[];
}

/** Fetch every resolved type definition from the platform. */
export async function getResolvedTypes(): Promise<ServerTypeEntry[]> {
  const res = await get<{ types: ServerTypeEntry[] }>('/types/all');
  return res.types ?? [];
}
