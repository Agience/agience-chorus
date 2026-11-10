/**
 * A timer's job grant is approved at Origin's own page, in a window the app opens (2026-11-10):
 * the app takes the grant's id only from that window, at Origin's own origin, for the job it asked.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('../../config/runtime', () => ({
  getRuntimeConfig: () => ({ originUri: 'https://origin.test' }),
}));

import { approveTimerAtOrigin, revokeAtOrigin } from '../jobGrants';

let popup: { closed: boolean };
let opened: string[];

beforeEach(() => {
  popup = { closed: false };
  opened = [];
  vi.spyOn(window, 'open').mockImplementation(((url: string) => {
    opened.push(url);
    return popup as unknown as Window;
  }) as typeof window.open);
});

afterEach(() => vi.restoreAllMocks());

function answer(data: object, origin = 'https://origin.test', source: unknown = popup) {
  window.dispatchEvent(new MessageEvent('message', { data, origin, source: source as Window }));
}

describe('api/jobGrants', () => {
  it("opens Origin's page with the grant to approve and this app's origin", async () => {
    const done = approveTimerAtOrigin('t1', ['t1', 'wf-1'], 'Digest');
    const url = new URL(opened[0]);
    expect(url.origin + url.pathname).toBe('https://origin.test/job-grant');
    expect(Object.fromEntries(url.searchParams)).toEqual({
      job: 'lumen.timer.t1', reach: 't1,wf-1', title: 'Digest', days: '30', back: window.location.origin });
    answer({ type: 'agience.job-grant', job: 'lumen.timer.t1', grant_id: 'jg-1' });
    await expect(done).resolves.toBe('jg-1');
  });

  it('takes no answer from another origin, another window or another job', async () => {
    const done = approveTimerAtOrigin('t1', ['t1'], 'Digest');
    answer({ type: 'agience.job-grant', job: 'lumen.timer.t1', grant_id: 'evil' }, 'https://evil.test');
    answer({ type: 'agience.job-grant', job: 'lumen.timer.t1', grant_id: 'evil' }, 'https://origin.test', window);
    answer({ type: 'agience.job-grant', job: 'lumen.timer.t2', grant_id: 'other' });
    answer({ type: 'agience.job-grant', job: 'lumen.timer.t1', grant_id: 'jg-1' });
    await expect(done).resolves.toBe('jg-1');
  });

  it('a declined or closed window refuses, in words', async () => {
    const declined = approveTimerAtOrigin('t1', ['t1'], 'Digest');
    answer({ type: 'agience.job-grant-declined' });
    await expect(declined).rejects.toThrow('You did not approve it at Origin.');
    vi.useFakeTimers();
    try {
      const closed = approveTimerAtOrigin('t1', ['t1'], 'Digest');
      popup.closed = true;
      vi.advanceTimersByTime(600);
      await expect(closed).rejects.toThrow("Origin's window closed before it was approved.");
    } finally {
      vi.useRealTimers();
    }
  });

  it('a blocked window says how to allow it', async () => {
    vi.spyOn(window, 'open').mockReturnValue(null);
    await expect(approveTimerAtOrigin('t1', ['t1'], 'Digest')).rejects.toThrow('allow pop-ups');
  });

  it('a revoke resolves on Origin saying that grant is stopped', async () => {
    const done = revokeAtOrigin('jg-1', 'Digest');
    expect(new URL(opened[0]).searchParams.get('revoke')).toBe('jg-1');
    answer({ type: 'agience.job-grant-revoked', grant_id: 'jg-2' });
    answer({ type: 'agience.job-grant-revoked', grant_id: 'jg-1' });
    await expect(done).resolves.toBeUndefined();
  });
});
