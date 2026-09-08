// api/search.ts
//
// Recall — Mantle's ordered read over the lattice.
//
// ⛔ THE ENDPOINT IS `/artifacts/recall`, NOT `/artifacts/search`. This module called the latter
// until 2026-08-27; Mantle's live surface has no such route, so every search in the app answered
// 404 and the failure was invisible to the suite, which mocks `./api` and therefore asserted only
// that the dead path was the one requested. Measured against the live node's `/openapi.json`:
// 36 paths, `/artifacts/recall` among them and no `/artifacts/search`.
//
// The rename carried a shape change on both legs, and each half was a separate silent failure:
//   · `from` -> `from_`   an unread field defaults to 0, so every page but the first would have
//                         returned page one while reporting the offset asked for.
//   · `use_hybrid`, `aperture`  GONE. `artifacts_router.py:423` says of them: "none is read on any
//                         path". They were never load-bearing; sending them claimed a control the
//                         API does not have.
//   · `used_hybrid` -> `ordering`  the response says what ORDERED the recall — `"coverage"` (the
//                         query's own stem count) or the node's ontology ranking. That is a real
//                         answer to "why these, in this order"; a hybrid-vector boolean is not,
//                         and this platform's retrieval is model-free by canon.
import api from './api';
import type {
  SearchRequest,
  SearchResponse,
  SuggestionsRequest,
  SuggestionsResponse,
  SearchHit,
} from './types/search';

/** The wire request, exactly as `ArtifactRecallRequest` declares it. */
type RecallRequest = {
  query_text: string;
  scope?: string[];
  from_?: number;
  size?: number;
  sort?: 'relevance' | 'recency';
  highlight?: boolean;
};

type RecallHit = {
  id: string;
  score: number;
  root_id: string;
  version_id: string;
  collection_id?: string;
};

/** `ArtifactRecallResponse`. Note `from_`, matching the request. */
type RecallResponse = {
  hits: RecallHit[];
  total: number;
  query_text: string;
  parsed_query?: string;
  corrections?: string[];
  ordering?: string;
  from_: number;
  size: number;
};

/**
 * One recall, scoped or not.
 *
 * The three exported callers differed only in `scope`, so they share this rather than carrying
 * three copies of a body that has now been wrong three times over in the same way.
 */
async function recall(request: SearchRequest, scope?: string[]): Promise<SearchResponse> {
  const body: RecallRequest = {
    query_text: request.query_text,
    scope,
    from_: request.from_ ?? 0,
    size: request.size ?? 20,
    sort: request.sort ?? 'relevance',
    highlight: request.highlight ?? true,
  };
  const resp = await api.post<RecallResponse>('/artifacts/recall', body);
  return mapRecallResponse(resp.data);
}

/** Recall within one workspace. */
export function searchWorkspace(request: SearchRequest): Promise<SearchResponse> {
  return recall(request, request.collection_id ? [request.collection_id] : undefined);
}

/** Recall within one collection. */
export function searchCollection(request: SearchRequest): Promise<SearchResponse> {
  return recall(request, request.collection_id ? [request.collection_id] : undefined);
}

/** Recall across everything the caller can reach — no scope. */
export function searchGlobal(request: SearchRequest): Promise<SearchResponse> {
  return recall(request);
}

/**
 * Get autocomplete suggestions for workspace search
 */
export async function getWorkspaceSuggestions(request: SuggestionsRequest): Promise<SuggestionsResponse> {
  // Suggestions are not available server-side; return empty to avoid 404s.
  void request; // mark used
  return { tags: [], titles: [] };
}

/**
 * Get autocomplete suggestions for collection search
 */
export async function getCollectionSuggestions(request: SuggestionsRequest): Promise<SuggestionsResponse> {
  // Suggestions are not available server-side; return empty to avoid 404s.
  void request; // mark used
  return { tags: [], titles: [] };
}

// Map Mantle's recall response to the shape the UI reads.
function mapRecallResponse(data: RecallResponse): SearchResponse {
  const hits: SearchHit[] = (data?.hits || []).map((h: RecallHit) => ({
    id: h.id,
    score: h.score,
    root_id: h.root_id,
    version_id: h.version_id,
    collection_id: h.collection_id,
  }));

  return {
    hits,
    total: data?.total ?? hits.length,
    query_text: data?.query_text ?? '',
    parsed_query: data?.parsed_query,
    corrections: data?.corrections ?? [],
    ordering: data?.ordering,
    from: data?.from_ ?? 0,
    size: data?.size ?? 20,
  };
}
