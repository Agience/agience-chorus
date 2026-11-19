/** `api/recents`: the person's recents are found once through Crystal and read and visited by op. */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const post = vi.fn();
vi.mock('../api', () => ({ post: (...a: unknown[]) => post(...a) }));

describe('recents', () => {
  beforeEach(() => {
    vi.resetModules();
    post.mockReset();
  });

  it('finds the collection once, then reads and visits it by op', async () => {
    post.mockImplementation(async (url: string) =>
      url === '/create' ? { id: 'r1' } : { items: [{ id: 'w1' }] });
    const { listRecents, visitRecent } = await import('../recents');
    expect(await listRecents()).toEqual([{ id: 'w1' }]);
    await visitRecent('w1');
    expect(post.mock.calls).toEqual([
      ['/create', { content_type: 'application/vnd.agience.recents+json' }],
      ['/artifacts/r1/op/view', {}],
      ['/artifacts/r1/op/visit', { id: 'w1' }],
    ]);
  });
});
