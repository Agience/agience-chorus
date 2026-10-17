// A removal says where from and offers a way back: Undo re-links an unlink; Restore restores an
// artifact that was archived because nothing else held it.
import { describe, it, expect, vi, beforeEach } from 'vitest';

const { toastMock, updateArtifactMock } = vi.hoisted(() => ({ toastMock: vi.fn(), updateArtifactMock: vi.fn() }));
vi.mock('sonner', () => ({ toast: Object.assign(toastMock, { error: vi.fn() }) }));
vi.mock('../../api/artifacts', () => ({ updateArtifact: updateArtifactMock }));

import { announceRemoval } from '../removal';

describe('announceRemoval', () => {
  beforeEach(() => { toastMock.mockReset(); updateArtifactMock.mockReset().mockResolvedValue({}); });

  it('offers Undo for an unlink, which re-links', async () => {
    const relink = vi.fn().mockResolvedValue({});
    announceRemoval({ id: 'a1', removed: true, archived: false }, { from: 'Inbox', relink });
    const [title, opts] = toastMock.mock.calls[0];
    expect(title).toBe('Removed from Inbox');
    opts.action.onClick();
    expect(relink).toHaveBeenCalled();
  });

  it('offers Restore when the removal archived the artifact', async () => {
    const relink = vi.fn();
    announceRemoval({ id: 'a1', removed: true, archived: true }, { from: 'Inbox', relink });
    const [title, opts] = toastMock.mock.calls[0];
    expect(title).toBe('Archived');
    expect(opts.description).toContain('Archived filter');
    opts.action.onClick();
    expect(updateArtifactMock).toHaveBeenCalledWith('a1', { state: 'live' });
    expect(relink).not.toHaveBeenCalled();
  });
});
