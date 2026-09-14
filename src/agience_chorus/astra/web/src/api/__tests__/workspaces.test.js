import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api', () => {
  return {
    get: vi.fn(),
    getList: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    del: vi.fn(),
    put: vi.fn(),
  };
});

import { get, getList, post, patch } from '../api';
import {
  listWorkspaces,
  createWorkspace,
  listWorkspaceArtifacts,
  orderWorkspaceArtifacts,
  getArtifactContentUrl,
} from '../workspaces';

describe('api/workspaces', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('listWorkspaces filters /artifacts/visible by workspace content_type', async () => {
    getList.mockResolvedValueOnce([{ id: 'w1' }]);
    const res = await listWorkspaces();
    expect(getList).toHaveBeenCalledWith('/artifacts/visible?content_type=application%2Fvnd.agience.workspace%2Bjson');
    expect(res).toEqual([{ id: 'w1' }]);
  });

  it('createWorkspace calls POST /artifacts with workspace content_type', async () => {
    post.mockResolvedValueOnce({ id: 'w-new', name: 'N' });
    const res = await createWorkspace({ name: 'N', description: 'D' });
    expect(post).toHaveBeenCalledWith('/artifacts', { name: 'N', description: 'D', content_type: 'application/vnd.agience.workspace+json' });
    expect(res.id).toBe('w-new');
  });

  it('listWorkspaceArtifacts normalizes array response to { items }', async () => {
    get.mockResolvedValueOnce([{ id: 'c1' }, { id: 'c2' }]);
    const res = await listWorkspaceArtifacts('w1');
    expect(get).toHaveBeenCalledWith('/artifacts/w1/children');
    expect(res).toEqual({ items: [{ id: 'c1' }, { id: 'c2' }] });
  });

  it('listWorkspaceArtifacts preserves object response with order_version', async () => {
    get.mockResolvedValueOnce({ items: [{ id: 'c1' }], order_version: 3 });
    const res = await listWorkspaceArtifacts('w2');
    expect(get).toHaveBeenCalledWith('/artifacts/w2/children');
    expect(res).toEqual({ items: [{ id: 'c1' }], order_version: 3 });
  });

  it('orderWorkspaceArtifacts calls PATCH /artifacts/:id/children/order', async () => {
    patch.mockResolvedValueOnce({ order_version: 5 });
    const res = await orderWorkspaceArtifacts('w1', ['a', 'b'], 4);
    expect(patch).toHaveBeenCalledWith('/artifacts/w1/children/order', { ordered_ids: ['a', 'b'], order_version: 4 });
    expect(res).toEqual({ ok: true, version: 5 });
  });

  it('getArtifactContentUrl calls GET /artifacts/:id/content-url', async () => {
    get.mockResolvedValueOnce({ url: 'https://cdn', expires_in: 300 });
    const res = await getArtifactContentUrl('w1', 'c1');
    expect(get).toHaveBeenCalledWith('/artifacts/c1/content-url');
    expect(res.expires_in).toBe(300);
  });

});
