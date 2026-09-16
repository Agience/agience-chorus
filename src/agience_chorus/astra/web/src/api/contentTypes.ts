// api/contentTypes.ts
//
// Runtime content-type discovery. Crystal — the gateway — is the single source of resolved type
// definitions: personas register the types they own through `POST /register`, and `GET /types/all`
// is the bulk read of that registry. Facet hydrates from it at runtime and compiles no server type
// in, so a persona that publishes a new type needs no Facet rebuild.
//
// ⚠ THE CALL IS ROUTED BY `api.ts`, NOT BY THIS MODULE'S BASE URL. `isCrystalTypePath` sends
// `/types/*` to `CRYSTAL_URI`; the axios default is Mantle, which carries a `types_service` of its
// own that nothing populates. Routed there this returns `{types: []}` on every node — an empty
// catalogue that looks like a node with no types rather than a call to the wrong service.

import { get } from './api';

/** One resolved type definition, as Crystal's `GET /types/all` serves it. */
export interface ServerTypeEntry {
  content_type: string;
  /** The definition the owning persona pushed, carrying its nested `ui` block. Opaque here. */
  definition: Record<string, unknown>;
  /** Slug of the persona that registered it — `aria`, `lumen`, … */
  server?: string | null;
}

/** Fetch every resolved type definition from the platform. */
export async function getResolvedTypes(): Promise<ServerTypeEntry[]> {
  const res = await get<{ types: ServerTypeEntry[] }>('/types/all');
  return res.types ?? [];
}
