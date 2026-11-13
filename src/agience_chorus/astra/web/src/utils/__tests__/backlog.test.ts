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

// The one Status-line rule (G6), from the file every reader tests against.
import { isClosedStatus, statusLine } from '../backlog';
import RULE_JSON from '../../../../../lumen/ui/application/vnd.agience.backlog-item+json/status-line.json';

const RULE = RULE_JSON as { cases: { text: string; status: string | null; closed: boolean }[] };

describe('a Markdown report’s Status line', () => {
  it.each(RULE.cases)('$text', ({ text, status, closed }) => {
    expect(statusLine(text)).toBe(status);
    expect(isClosedStatus(statusLine(text))).toBe(closed);
  });

  it('closes a Markdown report by its Status line, and leaves other text alone', () => {
    const md = (content: string) => ({ id: 'm', state: 'committed', content,
      context: JSON.stringify({ content_type: 'text/markdown' }) }) as unknown as Artifact;
    expect(isClosedBacklogItem(md('BUG-1 x\nStatus: closed in 202611.12.2'))).toBe(true);
    expect(isClosedBacklogItem(md('BUG-2 x\nStatus: verified 2026.11.24'))).toBe(false);
    expect(isClosedBacklogItem(md('A note that mentions\nStatus: closed\nin passing'))).toBe(true);
  });
});
