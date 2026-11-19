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
import type { Artifact } from './types/artifact';

/** The wire request, exactly as `ArtifactRecallRequest` declares it. */
type RecallRequest = {
  query_text: string;
  scope?: string[];
  from_?: number;
  size?: number;
  sort?: 'relevance' | 'recency';
  highlight?: boolean;
  state?: 'live' | 'archived';
  artifacts?: boolean;
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
  applied_filters?: string[];
  from_: number;
  size: number;
  artifacts?: Artifact[];
};

/**
 * One recall, scoped or not.
 *
 * The three exported callers differed only in `scope`, so they share this rather than carrying
 * three copies of a body that has now been wrong three times over in the same way.
 */
async function recall(request: SearchRequest, scope?: string[]): Promise<SearchResponse> {
  const body: RecallRequest = {
    query_text: composedQuery(request),
    scope,
    from_: request.from_ ?? 0,
    size: request.size ?? 20,
    sort: request.sort ?? 'relevance',
    highlight: request.highlight ?? true,
    artifacts: true,
    ...(request.state === 'archived' ? { state: 'archived' as const } : {}),
  };
  if (body.query_text?.trim() && body.sort === 'relevance' && !body.state) {
    try {
      const ranked = await runPlatformSearch(body);
      if (ranked) return ranked;
    } catch (e) {
      console.warn('[search] the platform Search did not run; reading the plain recall', e);
    }
  }
  const resp = await api.post<RecallResponse>('/artifacts/recall', body);
  return mapRecallResponse(resp.data);
}

/** What `search.run` answers: Mantle's hits, ordered by the Search's rank keys. */
type SearchRunResponse = { hits: RecallHit[]; total: number; search_id?: string };

let platformSearch: Promise<string | null> | null = null;

/** The platform Search artifact's id, as Mantle names it, read once. */
function platformSearchId(): Promise<string | null> {
  if (!platformSearch) {
    platformSearch = api.get<{ search?: string | null }>('/artifacts/platform-operators')
      .then((r) => r.data?.search ?? null)
      .catch((e) => { platformSearch = null; throw e; });
  }
  return platformSearch;
}

/** Forgets the platform Search's id, so the next search reads it again (a new sign-in). */
export function forgetPlatformSearch(): void {
  platformSearch = null;
}

/** The search panel's `exact`, `tag` and `types` written into the query text as the filters they
 * stand for. Mantle runs the text as it is. */
function composedQuery(body: SearchRequest): string {
  const parts: string[] = [];
  const text = body.query_text.trim();
  if (text) parts.push(body.exact ? `="${text.replace(/"/g, '')}"` : text);
  const tag = (body.tag ?? '').trim();
  if (tag) parts.push(body.tag_exact ? `tag:="${tag.replace(/"/g, '')}"` : `tag:${tag.replace(/\s+/g, '')}`);
  const types = (body.types ?? []).map((t) => t.trim()).filter((t) => t && !t.includes(','));
  if (types.length) parts.push(`type:${types.join(',')}`);
  return parts.join(' ');
}

/**
 * A text search runs the platform Search artifact in Crystal: Mantle answers what the caller may
 * read, and the Search orders it. The page's artifacts are read in one batch, in hit order. Null when the node
 * names no platform Search.
 */
async function runPlatformSearch(body: RecallRequest): Promise<SearchResponse | null> {
  const searchId = await platformSearchId();
  if (!searchId) return null;
  const queryText = body.query_text;
  const run = await api.post<SearchRunResponse>(
    `/artifacts/${encodeURIComponent(searchId)}/op/invoke`,
    { query_text: queryText, from: body.from_ ?? 0, size: body.size ?? 20,
      ...(body.scope ? { scope: body.scope } : {}) },
  );
  const hits = run.data?.hits ?? [];
  const rootIds = [...new Set(hits.map((h) => h.root_id).filter(Boolean))];
  let artifacts: Artifact[] = [];
  if (rootIds.length) {
    const page = await api.post<Artifact[] | { items?: Artifact[] }>(
      '/artifacts/batch', { artifact_ids: rootIds, include_archived: true });
    const data = page.data;
    const byId = new Map((Array.isArray(data) ? data : data?.items ?? []).map((a) => [a.id, a]));
    artifacts = rootIds.flatMap((id) => (byId.has(id) ? [byId.get(id) as Artifact] : []));
  }
  return mapRecallResponse({
    hits, total: run.data?.total ?? hits.length, query_text: queryText, ordering: 'search',
    from_: body.from_ ?? 0, size: body.size ?? 20, artifacts,
  });
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
    applied_filters: data?.applied_filters ?? [],
    from: data?.from_ ?? 0,
    size: data?.size ?? 20,
    artifacts: data?.artifacts ?? [],
  };
}

/**
 * What the platform Search finds for `query` among artifacts of `types`, as ids in its order.
 * The Search artifact holds the rank and size; this only runs it.
 */
export async function searchChoices(query: string, types: string[]): Promise<string[]> {
  const queryText = composedQuery({ query_text: query, types });
  const searchId = await platformSearchId().catch(() => null);
  const hits = searchId
    ? (await api.post<SearchRunResponse>(`/artifacts/${encodeURIComponent(searchId)}/op/invoke`,
      { query_text: queryText, from: 0, size: 20 })).data?.hits ?? []
    : (await api.post<RecallResponse>('/artifacts/recall',
      { query_text: queryText, highlight: false })).data?.hits ?? [];
  return hits.flatMap((h) => (h.root_id && h.root_id !== h.id ? [h.id, h.root_id] : [h.id]));
}
