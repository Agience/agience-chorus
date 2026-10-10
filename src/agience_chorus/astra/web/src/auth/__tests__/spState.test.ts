import { beforeEach, describe, expect, it } from 'vitest';

import { consumeSpState, issueSpState } from '../spState';

describe('spState', () => {
  beforeEach(() => localStorage.clear());

  it('issues a 64-hex-char random state and accepts it once', () => {
    const a = issueSpState();
    expect(a).toMatch(/^[0-9a-f]{64}$/);
    expect(issueSpState()).not.toBe(a);
    expect(consumeSpState(a)).toBe(true);
    expect(consumeSpState(a)).toBe(false);
  });

  it('accepts any pending state, then clears every sibling', () => {
    const a = issueSpState();
    const b = issueSpState();
    const c = issueSpState();
    expect(consumeSpState(b)).toBe(true);
    expect(consumeSpState(a)).toBe(false);
    expect(consumeSpState(c)).toBe(false);
    expect(localStorage.getItem('agience.sp_state')).toBeNull();
  });

  it('a failed match leaves the pending states in place', () => {
    const a = issueSpState();
    expect(consumeSpState('forged')).toBe(false);
    expect(consumeSpState(a)).toBe(true);
  });

  it('refuses missing, unknown and expired states', () => {
    expect(consumeSpState(null)).toBe(false);
    expect(consumeSpState('')).toBe(false);
    issueSpState();
    expect(consumeSpState('unknown')).toBe(false);
    const old = issueSpState(Date.now() - 2 * 60 * 60 * 1000);
    expect(consumeSpState(old)).toBe(false);
  });

  it('survives corrupt storage', () => {
    localStorage.setItem('agience.sp_state', '{not json');
    expect(consumeSpState('x')).toBe(false);
    const s = issueSpState();
    expect(consumeSpState(s)).toBe(true);
  });
});
