import { describe, expect, it } from 'vitest';

import type { Artifact } from '@/context/workspace/workspace.types';
import { isClosedBacklogItem } from '../backlog';

// G6: a Backlog item its loop closed leaves the open Backlog. The item's own state lives in its
// context; the artifact's state (draft, committed, archived) is a different thing.
const item = (ctx: Record<string, unknown>, state = 'committed') =>
  ({ id: 'a', state, context: JSON.stringify(ctx) }) as unknown as Artifact;

describe('isClosedBacklogItem', () => {
  it('is true for a Backlog item whose state is closed', () => {
    expect(isClosedBacklogItem(item({ content_type: 'application/vnd.agience.backlog-item+json',
                                       state: 'closed', closed_in: '202611.12.2' }))).toBe(true);
  });
  it('is false for an open, shipped or untyped item', () => {
    for (const state of ['open', 'working', 'in_cut', 'validated', 'shipped']) {
      expect(isClosedBacklogItem(item({ content_type: 'application/vnd.agience.backlog-item+json',
                                         state }))).toBe(false);
    }
    expect(isClosedBacklogItem(item({ content_type: 'text/markdown', state: 'closed' }))).toBe(false);
  });
  it('ignores the artifact state', () => {
    expect(isClosedBacklogItem(item({ content_type: 'application/vnd.agience.backlog-item+json',
                                       state: 'open' }, 'archived'))).toBe(false);
  });
});
