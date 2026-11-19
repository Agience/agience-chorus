import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api', () => {
  return {
    get: vi.fn(),
    getList: vi.fn(),
    LIST_PAGE: 500,
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
  updateWorkspace,
  addArtifactToWorkspace,
  updateWorkspaceArtifact,
  listWorkspaceArtifacts,
  moveWorkspaceArtifacts,
  getArtifactContentUrl,
} from '../workspaces';

describe('api/workspaces', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('listWorkspaces asks Crystal for the workspaces the caller sees, oldest first', async () => {
    getList.mockResolvedValueOnce([{ id: 'w1' }]);
    const res = await listWorkspaces();
    expect(getList).toHaveBeenCalledWith('/types/visible?content_type=application%2Fvnd.agience.workspace%2Bjson');
    expect(res).toEqual([{ id: 'w1' }]);
  });

  it('listWorkspaces lays the marks Crystal declares over the listing by id', async () => {
    getList.mockResolvedValueOnce([{ id: 'w1', name: 'Notes' }, { id: 'w2', name: 'Notes' }, { id: 'w3' }]);
    get.mockResolvedValueOnce({ marks: { w1: { label_at: 'day' }, w2: { label_at: 'day' } } });
    const res = await listWorkspaces();
    expect(get).toHaveBeenCalledWith('/marks?content_type=application%2Fvnd.agience.workspace%2Bjson');
    expect(res).toEqual([{ id: 'w1', name: 'Notes', label_at: 'day' },
      { id: 'w2', name: 'Notes', label_at: 'day' }, { id: 'w3' }]);
  });

  it('a workspace and what it holds are changed through PATCH /artifacts/:id', async () => {
    await updateWorkspace('w1', { name: 'Plans' });
    await updateWorkspaceArtifact('w1', 'a1', { context: '{}' });
    expect(patch).toHaveBeenCalledWith('/artifacts/w1', { name: 'Plans' });
    expect(patch).toHaveBeenCalledWith('/artifacts/a1', { context: '{}' });
    expect(post).not.toHaveBeenCalled();
  });

  it('listWorkspaces still lists when Crystal gives no marks', async () => {
    getList.mockResolvedValueOnce([{ id: 'w1' }]);
    get.mockRejectedValueOnce(new Error('down'));
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    expect(await listWorkspaces()).toEqual([{ id: 'w1' }]);
    warn.mockRestore();
  });

  it('createWorkspace has Crystal name it, then makes it at /artifacts', async () => {
    const body = {
      name: 'N', description: 'D', content_type: 'application/vnd.agience.workspace+json',
      context: JSON.stringify({ content_type: 'application/vnd.agience.workspace+json', title: 'N' }),
    };
    post.mockResolvedValueOnce(body).mockResolvedValueOnce({ id: 'w-new', name: 'N' });
    const res = await createWorkspace({ name: 'N', description: 'D' });
    expect(post).toHaveBeenNthCalledWith(1, '/types/name', body);
    expect(post).toHaveBeenNthCalledWith(2, '/artifacts', body);
    expect(res.id).toBe('w-new');
  });

  it('a create is named at Crystal, which writes nothing, and made at Mantle', async () => {
    const named = { container_id: 'w1', context: '{"content_type":"text/markdown","title":"Untitled Note"}', name: 'Untitled Note' };
    post.mockResolvedValueOnce(named).mockResolvedValueOnce({ id: 'x' });
    await addArtifactToWorkspace('w1', { context: '{"content_type":"text/markdown"}' });
    expect(post).toHaveBeenNthCalledWith(1, '/types/name', { container_id: 'w1', context: '{"content_type":"text/markdown"}' });
    expect(post).toHaveBeenNthCalledWith(2, '/artifacts', named);
  });

  it('listWorkspaceArtifacts normalizes array response to { items }', async () => {
    get.mockResolvedValueOnce([{ id: 'c1' }, { id: 'c2' }]);
    const res = await listWorkspaceArtifacts('w1');
    expect(get).toHaveBeenCalledWith('/artifacts/w1/children', { params: { limit: 500 } });
    expect(res).toEqual({ items: [{ id: 'c1' }, { id: 'c2' }] });
  });

  it('listWorkspaceArtifacts preserves object response with order_version', async () => {
    get.mockResolvedValueOnce({ items: [{ id: 'c1' }], order_version: 3 });
    const res = await listWorkspaceArtifacts('w2');
    expect(get).toHaveBeenCalledWith('/artifacts/w2/children', { params: { limit: 500 } });
    expect(res).toEqual({ items: [{ id: 'c1' }], order_version: 3 });
  });

  it('moveWorkspaceArtifacts sends one move and no order key', async () => {
    patch.mockResolvedValueOnce({ order_version: 5 });
    const res = await moveWorkspaceArtifacts('w1', ['c'], 'a', 4);
    expect(patch).toHaveBeenCalledTimes(1);
    expect(patch).toHaveBeenCalledWith('/artifacts/w1/children/order', { move_ids: ['c'], before_id: 'a', order_version: 4 });
    expect(res).toEqual({ ok: true, version: 5 });
  });

  it('moveWorkspaceArtifacts with no target moves it last', async () => {
    patch.mockResolvedValueOnce({ order_version: 6 });
    await moveWorkspaceArtifacts('w1', ['a'], null);
    expect(patch).toHaveBeenCalledWith('/artifacts/w1/children/order', { move_ids: ['a'] });
  });

  it('getArtifactContentUrl calls GET /artifacts/:id/content-url', async () => {
    get.mockResolvedValueOnce({ url: 'https://cdn', expires_in: 300 });
    const res = await getArtifactContentUrl('w1', 'c1');
    expect(get).toHaveBeenCalledWith('/artifacts/c1/content-url');
    expect(res.expires_in).toBe(300);
  });

});
