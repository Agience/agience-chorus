import { beforeEach, describe, expect, it, vi } from 'vitest';

const getArtifactMock = vi.fn();
vi.mock('../artifacts', () => ({ getArtifact: (...a: unknown[]) => getArtifactMock(...a) }));

let feed: ((evt: { event: string; payload: unknown }) => void) | null = null;
vi.mock('../events', () => ({
  subscribeEvents: (_filter: unknown, cb: (evt: { event: string; payload: unknown }) => void) => {
    feed = cb;
    return () => { feed = null; };
  },
}));

import { completeFromFeed } from '../feedArtifact';
import { subscribeWorkspaceEvents } from '../workspaces';

// 2026-10-19: the title is part of an artifact's content and sealed at rest, so the change feed no
// longer carries it. A card shown from the feed's descriptor would lose its title.
const DESCRIPTOR = { id: 'a1', order_key: 'k', context: '{"kind":"note"}' } as never;

describe('a change-feed descriptor is completed through the authorized read', () => {
  beforeEach(() => { getArtifactMock.mockReset(); });

  it('takes the title from the read, keeping what only the feed carries', async () => {
    getArtifactMock.mockResolvedValue({ id: 'a1', context: '{"kind":"note","title":"Board figures"}' });
    const full = await completeFromFeed(DESCRIPTOR) as unknown as Record<string, string>;
    expect(getArtifactMock).toHaveBeenCalledWith('a1');
    expect(JSON.parse(full.context).title).toBe('Board figures');
    expect(full.order_key).toBe('k');
  });

  it('drops the untitled context when the read fails, so a merge keeps the title on screen', async () => {
    getArtifactMock.mockRejectedValue(new Error('403'));
    const full = await completeFromFeed(DESCRIPTOR) as unknown as Record<string, unknown>;
    expect('context' in full).toBe(false);
    const onScreen = { id: 'a1', context: '{"title":"Board figures"}' };
    expect({ ...onScreen, ...full }.context).toBe('{"title":"Board figures"}');
  });

  it("a workspace's created and updated cards arrive completed", async () => {
    getArtifactMock.mockResolvedValue({ id: 'a1', context: '{"title":"Board figures"}' });
    const created = vi.fn();
    const updated = vi.fn();
    subscribeWorkspaceEvents('ws-1', { onArtifactCreated: created, onArtifactUpdated: updated });
    feed!({ event: 'artifact.created', payload: { artifact: DESCRIPTOR } });
    feed!({ event: 'artifact.updated', payload: { artifact: DESCRIPTOR } });
    await vi.waitFor(() => expect(updated).toHaveBeenCalled());
    expect(JSON.parse(created.mock.calls[0][0].context).title).toBe('Board figures');
    expect(JSON.parse(updated.mock.calls[0][0].context).title).toBe('Board figures');
  });
});
