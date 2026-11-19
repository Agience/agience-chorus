// api/types/collection.ts

// Body you POST to /artifacts (with content_type set to the collection type) to create a collection
export interface CollectionCreate {
  name: string;
  description?: string;
}

// Body you PATCH to /artifacts/{id} to update a collection
export interface CollectionUpdate {
  name?: string;
  description?: string;
}

// What GET /artifacts/{id} (or /artifacts/visible, filtered to the collection content type) returns
export interface CollectionResponse {
  id: string;
  name: string;
  description: string;
  created_by: string;
  created_time: string;   // ISO datetime
  modified_time: string;  // ISO datetime
  /** The collection that holds this one, when the stored artifact names it. */
  collection_id?: string | null;
  /** Holds the title (`context.title`); Mantle answers `name` as that title. */
  context?: unknown;
  /** The actions Mantle allows the caller on it; the Facet offers only these. */
  allowed_actions?: string[];
  /** Crystal marks a collection whose name another the caller can reach shares. */
  name_shared?: boolean;
  /** With `name_shared`: the shown name of the collection holding it, when that one is reachable. */
  place_in?: string;
  /** With `name_shared`: whether the caller made it, when that is known. */
  place_yours?: boolean;
}

export interface CollectionCommitResponse {
  id: string;
  message: string;
  author_id: string;
  subject_user_id?: string | null;
  presenter_type?: string | null;
  presenter_id?: string | null;
  client_id?: string | null;
  host_id?: string | null;
  server_id?: string | null;
  agent_id?: string | null;
  api_key_id?: string | null;
  confirmation?: string | null;
  changeset_type?: string | null;
  timestamp: string;
  item_ids: string[];
}


