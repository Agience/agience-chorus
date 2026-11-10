import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api', () => ({ get: vi.fn(), getList: vi.fn(), post: vi.fn(), postList: vi.fn(),
  patch: vi.fn(), del: vi.fn(), put: vi.fn() }));

import { post, del } from '../api';
import { setArtifactCollections } from '../collections';

describe('setArtifactCollections (BUG-020, BUG-021)', () => {
  beforeEach(() => vi.clearAllMocks());

  it('adds to each new collection, removes from each left, and returns what it now holds', async () => {
    post.mockResolvedValue({});
    del.mockResolvedValue({});
    const now = await setArtifactCollections(
      { id: 'v1', root_id: 'r1', committed_collection_ids: ['A', 'B'] }, ['B', 'C']);
    expect(now.sort()).toEqual(['B', 'C']);
    expect(post).toHaveBeenCalledWith('/artifacts', { container_id: 'C', source_artifact_id: 'v1' });
    expect(post).toHaveBeenCalledTimes(1);
    expect(del).toHaveBeenCalledTimes(1);
    expect(String(del.mock.calls[0][0])).toContain('A');
  });

  it('tries every change, then throws the first failure with what did change', async () => {
    post.mockRejectedValueOnce(new Error('403 refused')).mockResolvedValue({});
    del.mockResolvedValue({});
    const err = await setArtifactCollections(
      { id: 'v1', committed_collection_ids: ['A'] }, ['C', 'D']).catch((e) => e);
    expect(err.message).toBe('403 refused');
    expect(err.partial.sort()).toEqual(['D']);       // C refused, D added, A removed
    expect(del).toHaveBeenCalledTimes(1);
  });
});
