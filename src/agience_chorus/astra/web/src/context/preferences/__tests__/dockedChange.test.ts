// BUG-016 (2026-11-10): a tab with an older docked list wrote it back and undocked what another
// tab had docked since. A change is applied as this page's additions and removals, to the server's
// list as it is now.
import { describe, expect, it } from 'vitest';

import { withDockedChange } from '../dockedChange';

const prefs = (ids?: string[], extra: Record<string, unknown> = {}) =>
  ({ browser: { ...extra, ...(ids ? { dockedWorkspaceCardIds: ids } : {}) } });

describe('a change to the docked tabs', () => {
  it('keeps what another tab docked since this one read the list', async () => {
    const local = prefs(['inbox']);                          // this tab read only the Inbox
    const server = prefs(['inbox', 'agience', 'general']);   // another tab docked two since
    const out = await withDockedChange(prefs(['inbox', 'notes']), local, async () => server);
    expect(out.browser).toEqual({ dockedWorkspaceCardIds: ['inbox', 'agience', 'general', 'notes'] });
  });

  it('removes only what this tab closed', async () => {
    const out = await withDockedChange(prefs(['agience']), prefs(['inbox', 'agience']),
                                       async () => prefs(['inbox', 'agience', 'general']));
    expect(out.browser).toEqual({ dockedWorkspaceCardIds: ['agience', 'general'] });
  });

  it('keeps the server\'s other browser settings and leaves other writes alone', async () => {
    const out = await withDockedChange(prefs(['a', 'b']), prefs(['a']),
                                       async () => prefs(['a'], { view: 'list' }));
    expect(out.browser).toEqual({ view: 'list', dockedWorkspaceCardIds: ['a', 'b'] });
    const layout = { layout: { sidebarWidth: 300 } };
    expect(await withDockedChange(layout, prefs(['a']), async () => { throw new Error('unused'); }))
      .toBe(layout);
  });

  it('writes as before when the server cannot be read or holds no list', async () => {
    const write = prefs(['a']);
    expect(await withDockedChange(write, prefs([]), async () => { throw new Error('offline'); })).toBe(write);
    expect(await withDockedChange(write, prefs([]), async () => prefs())).toBe(write);
  });
});
