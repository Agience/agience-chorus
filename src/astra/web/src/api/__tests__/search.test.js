// api/search — the recall contract.
//
// ⛔ THIS FILE PREVIOUSLY ASSERTED THE DEAD ENDPOINT. It pinned `'/artifacts/search'`, a path
// Mantle does not serve, so it stayed green for exactly as long as search was completely broken.
// A mocked transport can only ever assert what the app MEANT to call, which is why the assertions
// below name the shape measured against the live node's `/openapi.json` (2026-08-27) rather than
// the shape this module used to send.
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api', () => {
  return {
    default: {
      post: vi.fn(),
    },
  };
});

import api from '../api';
import { searchGlobal, searchWorkspace, searchCollection, getWorkspaceSuggestions, getCollectionSuggestions } from '../search';

// `ArtifactRecallResponse`, as the live schema declares it: `from_`, and `ordering` where
// `used_hybrid` used to be.
const mkRecall = (overrides = {}) => ({
  hits: [
    { id: 'h1', score: 1.23, root_id: 'r1', version_id: 'v1', workspace_id: 'w1' },
    { id: 'h2', score: 0.5, root_id: 'r2', version_id: 'v2', collection_id: 'c1' },
  ],
  total: 2,
  query_text: 'foo',
  ordering: 'coverage',
  from_: 0,
  size: 20,
  ...overrides,
});

describe('api/search (POST /artifacts/recall)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('searchGlobal posts to /artifacts/recall and maps the response', async () => {
    api.post.mockResolvedValueOnce({ data: mkRecall() });
    const res = await searchGlobal({ query_text: 'foo' });
    expect(api.post).toHaveBeenCalledWith(
      '/artifacts/recall',
      expect.objectContaining({
        query_text: 'foo',
        from_: 0,
        size: 20,
        sort: 'relevance',
        highlight: true,
      })
    );
    expect(res.total).toBe(2);
    expect(res.hits[0]).toEqual(expect.objectContaining({ id: 'h1', root_id: 'r1', version_id: 'v1' }));
  });

  it('sends `from_`, never `from` — an unread offset silently returns page one', async () => {
    api.post.mockResolvedValueOnce({ data: mkRecall({ from_: 40 }) });
    const res = await searchGlobal({ query_text: 'foo', from_: 40, size: 20 });
    const [, body] = api.post.mock.calls[0];
    expect(body.from_).toBe(40);
    expect(body.from).toBeUndefined();
    // and the response's `from_` is what the UI reads as `from`
    expect(res.from).toBe(40);
  });

  it('sends no field Mantle does not read', async () => {
    api.post.mockResolvedValueOnce({ data: mkRecall() });
    // `aperture` is still accepted by the caller-facing type's older shape; it must not travel.
    await searchGlobal({ query_text: 'foo', aperture: 0.9 });
    const [, body] = api.post.mock.calls[0];
    for (const dead of ['use_hybrid', 'aperture', 'content_types']) {
      expect(body[dead]).toBeUndefined();
    }
    expect(Object.keys(body).sort()).toEqual(
      ['from_', 'highlight', 'query_text', 'scope', 'size', 'sort'].sort()
    );
  });

  it('searchWorkspace adds scope', async () => {
    api.post.mockResolvedValueOnce({ data: mkRecall() });
    await searchWorkspace({ query_text: 'bar', collection_id: 'w1' });
    const [, body] = api.post.mock.calls[0];
    expect(body.scope).toEqual(['w1']);
    expect(body.source_types).toBeUndefined();
  });

  it('searchCollection adds scope', async () => {
    api.post.mockResolvedValueOnce({ data: mkRecall() });
    await searchCollection({ query_text: 'baz', collection_id: 'c1' });
    const [, body] = api.post.mock.calls[0];
    expect(body.scope).toEqual(['c1']);
    expect(body.source_types).toBeUndefined();
  });

  it('searchGlobal sends no scope at all — everything the caller can reach', async () => {
    api.post.mockResolvedValueOnce({ data: mkRecall() });
    await searchGlobal({ query_text: 'foo' });
    const [, body] = api.post.mock.calls[0];
    expect(body.scope).toBeUndefined();
  });

  it('carries `ordering` through — what ordered the recall, when the node says', async () => {
    api.post.mockResolvedValueOnce({ data: mkRecall({ ordering: 'ontology' }) });
    const res = await searchGlobal({ query_text: 'foo' });
    expect(res.ordering).toBe('ontology');
  });

  it('defaults gracefully when the backend returns null/undefined data', async () => {
    api.post.mockResolvedValueOnce({ data: null });
    const res = await searchGlobal({ query_text: 'empty' });
    expect(res.hits).toEqual([]);
    expect(res.total).toBe(0);
    // A node is entitled not to say what ordered the recall; absent is absent, not `false`.
    expect(res.ordering).toBeUndefined();
  });

  describe('getWorkspaceSuggestions', () => {
    it('returns empty tags and titles without making an API call', async () => {
      const res = await getWorkspaceSuggestions({ query_text: 'art', workspace_id: 'ws-1' });
      expect(res).toEqual({ tags: [], titles: [] });
      expect(api.post).not.toHaveBeenCalled();
    });
  });

  describe('getCollectionSuggestions', () => {
    it('returns empty tags and titles without making an API call', async () => {
      const res = await getCollectionSuggestions({ query_text: 'doc', collection_id: 'c-1' });
      expect(res).toEqual({ tags: [], titles: [] });
      expect(api.post).not.toHaveBeenCalled();
    });
  });
});
