/** `api/drops`: the request a drop builds. The transport is mocked. */
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api', () => ({ post: vi.fn(() => Promise.resolve({ accepted: ['a'], refused: [] })) }));

import { post } from '../api';
import { dropOn } from '../drops';

describe('dropOn', () => {
  beforeEach(() => vi.mocked(post).mockClear());

  it('posts the ids to the target artifact drop op', async () => {
    const got = await dropOn('t/1', ['a', 'b']);
    expect(post).toHaveBeenCalledWith('/artifacts/t%2F1/op/drop', { ids: ['a', 'b'] });
    expect(got.accepted).toEqual(['a']);
  });

  it('names the workspace when there is one', async () => {
    await dropOn('t1', ['a'], 'ws1');
    expect(post).toHaveBeenCalledWith('/artifacts/t1/op/drop', { ids: ['a'], workspace_id: 'ws1' });
  });
});
