// api/types/artifact.ts

export type JSONValue = string | number | boolean | null | JSONValue[] | { [k: string]: JSONValue };

/** `live` is every artifact that is not archived. Legacy `committed`/`draft` values are mapped
 * to `live` at the API boundary (`utils/artifactState`). */
export type ArtifactState = 'live' | 'archived';

export interface ArtifactCreate {
  content_type?: string;
  context?: string;
  content: string;
  order_key?: string;
}

export interface ArtifactUpdate {
  context?: string;
  content?: string;
  state?: ArtifactState;
  order_key?: string;
}

export interface ArtifactResponse {
  id?: string;
  root_id?: string;
  collection_id?: string;
  content_type?: string;
  name?: string;
  description?: string;
  context: string;
  content: string;
  created_by?: string;
  created_time?: string;
  modified_by?: string;
  modified_time?: string;
  state: ArtifactState;
  order_key?: string;
  /**
   * Non-workspace collections this artifact belongs to (via edges).
   * Populated by `attach_committed_collection_ids()` on the backend.
   * Membership is edge-based and independent of artifact state.
   * (Backend field name is `committed_collection_ids` — a misnomer:
   * it lists memberships and has nothing to do with artifact state.)
   */
  committed_collection_ids?: string[];
  /** Every container holding this artifact, workspaces included: a workspace is a collection is an
   * artifact. `committed_collection_ids` leaves workspaces out, for the sharing checks. */
  container_ids?: string[];
  /** True when at least one child artifact exists (via parent_id edge). */
  has_children?: boolean;
  /** Number of child artifacts, if available. */
  child_count?: number;
  /** Set while the artifact is in Trash: who moved it there, and when. */
  trashed_by?: string;
  trashed_time?: string;
  /** In a Trash listing: when the artifact is deleted for good. */
  purge_after?: string;
}

export type Artifact = ArtifactResponse;
