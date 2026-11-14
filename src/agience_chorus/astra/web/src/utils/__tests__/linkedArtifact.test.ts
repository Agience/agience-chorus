/**
 * FR-030: a link to one artifact opens it when this person can read it, and is refused otherwise.
 */
import { describe, expect, it, vi } from 'vitest';

import { onLinkedArtifact, openLinkedArtifact, readLinkedArtifact } from '../linkedArtifact';

const art = { id: 'y-1', context: '{"title":"Y"}' };

describe('readLinkedArtifact', () => {
  it('reads it once', async () => {
    const read = vi.fn().mockResolvedValue(art);
    expect(await readLinkedArtifact('y-1', read)).toEqual(art);
    expect(read).toHaveBeenCalledTimes(1);
  });

  it('a link this person cannot read is refused', async () => {
    const read = vi.fn().mockRejectedValue(Object.assign(new Error('404'), { response: { status: 404 } }));
    expect(await readLinkedArtifact('y-1', read)).toBeNull();
    expect(read).toHaveBeenCalledTimes(1);
  });
});

describe('openLinkedArtifact', () => {
  it('holds an artifact asked for before the layout listens, and opens it once', () => {
    openLinkedArtifact(art as never);
    const fn = vi.fn();
    const off = onLinkedArtifact(fn);
    expect(fn).toHaveBeenCalledWith(art);
    openLinkedArtifact({ ...art, id: 'y-2' } as never);
    expect(fn).toHaveBeenCalledTimes(2);
    off();
    const later = vi.fn();
    onLinkedArtifact(later);
    expect(later).not.toHaveBeenCalled();
  });
});
