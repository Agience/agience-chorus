import { describe, expect, it } from 'vitest';

import { mergeViewContext } from '../mergeViewContext';

describe("a view's save keeps what was written to its card since it opened", () => {
  it('keeps a run record an operator wrote while the view was open', () => {
    const given = { title: 'Routine', key: { api_key_id: 'k1' } };
    const stored = { ...given, timer_state: { runs: 3, last_ok: false } };
    const fromView = { title: 'Routine', key: { api_key_id: 'k1', revoked_at: 't' } };
    expect(mergeViewContext(given, stored, fromView)).toEqual({
      title: 'Routine', key: { api_key_id: 'k1', revoked_at: 't' }, timer_state: { runs: 3, last_ok: false },
    });
  });

  it("applies what the view changed, including a key it removed", () => {
    const given = { title: 'a', timer: { results_to: 'log' }, note: 'x' };
    const stored = { ...given };
    const fromView = { title: 'b', timer: {} };
    expect(mergeViewContext(given, stored, fromView)).toEqual({ title: 'b', timer: {} });
  });

  it('does not bring back an old value over a newer stored one the view never touched', () => {
    const given = { title: 'a', item: { state: 'new' } };
    const stored = { title: 'a', item: { state: 'resolved' } };
    const fromView = { title: 'renamed', item: { state: 'new' } };
    expect(mergeViewContext(given, stored, fromView)).toEqual({ title: 'renamed', item: { state: 'resolved' } });
  });
});
