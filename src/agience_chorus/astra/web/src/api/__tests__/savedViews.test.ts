/** `api/savedViews`: a view is saved and run through Crystal. */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const post = vi.fn();
vi.mock('../api', () => ({ post: (...a: unknown[]) => post(...a) }));

import { runSavedView, saveView, VIEW_CONTENT_TYPE } from '../savedViews';

const choices = { apart: ['archived'], kinds: [], hidden_kinds: [], sort: 'recent' };

describe('saved views', () => {
  beforeEach(() => post.mockReset());

  it('saves a view of a collection with the choices in force, in the open workspace', async () => {
    post.mockResolvedValueOnce({ id: 'v1' });
    await saveView('c1', choices, 'w1');
    expect(post).toHaveBeenCalledWith('/create', {
      content_type: VIEW_CONTENT_TYPE, target_id: 'c1', choices, container_id: 'w1',
    });
  });

  it('saves without a container when none is open', async () => {
    post.mockResolvedValueOnce({ id: 'v1' });
    await saveView('c1', choices);
    expect(post.mock.calls[0][1]).not.toHaveProperty('container_id');
  });

  it('runs a saved view by its op', async () => {
    post.mockResolvedValueOnce({ target_id: 'c1', artifacts: [] });
    const got = await runSavedView('v 1');
    expect(post).toHaveBeenCalledWith('/artifacts/v%201/op/view', {});
    expect(got.target_id).toBe('c1');
  });
});
