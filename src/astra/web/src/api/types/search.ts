// api/types/search.ts

export interface SearchRequest {
  query_text: string;
  collection_id?: string;
  filters?: Record<string, unknown>;
  from_?: number;
  size?: number;
  use_vector?: boolean;
  use_bm25?: boolean;
  sort?: 'relevance' | 'recency';
  highlight?: boolean;
  // No `aperture`, and no `use_vector`/`use_bm25` equivalent on the wire: `ArtifactRecallRequest`
  // declares none of them, and mantle's own router says of the three it used to accept —
  // `aperture`, `use_hybrid`, `content_types` — that "none is read on any path"
  // (`artifacts_router.py:423`). `use_vector`/`use_bm25` above are read by the UI's advanced
  // panel and are not sent.
}

export interface SearchHitPresence {
  in_current_workspace: boolean;
  in_other_workspace: boolean;
  collections: string[];
}

export interface SearchHit {
  id: string;  // Document ID in search index
  score: number;
  root_id: string;  // Artifact root ID
  version_id: string;  // Version/artifact ID (for workspace artifacts, this is the artifact ID)
  collection_id?: string;  // Collection this artifact belongs to
}

export interface SearchFacetBucket {
  key: string;
  doc_count: number;
}

export interface SearchFacet {
  field: string;
  buckets: SearchFacetBucket[];
}

export interface SearchResponse {
  hits: SearchHit[];
  total: number;
  query_text: string;
  parsed_query?: string;
  corrections?: string[];
  /**
   * WHAT ORDERED THIS RECALL, as Mantle reports it — `"coverage"` (the query's own stem count,
   * which is what a node with no ontology bound answers) or the ordering its ontology host
   * supplies. Replaced `used_hybrid: boolean` on 2026-08-27: Mantle returns no such field, the
   * four places that set it all set it to `false`, and nothing ever read it. Optional, because a
   * node is entitled not to say.
   */
  ordering?: string;
  from: number;
  size: number;
}

export interface SuggestionsRequest {
  query_text: string;
  collection_id?: string;
  limit?: number;
  types?: ('tags' | 'titles')[];
}

export interface TagSuggestion {
  value: string;
  count: number;
}

export interface TitleSuggestion {
  id: string;
  title: string;
}

export interface SuggestionsResponse {
  tags?: TagSuggestion[];
  titles?: TitleSuggestion[];
}

