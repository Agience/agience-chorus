import { describe, expect, it } from 'vitest';

import { keyExpiry } from '../apiKeys';

describe('keyExpiry', () => {
  const now = Date.parse('2026-11-13T12:00:00Z');
  it('takes a time ahead, as ISO', () => {
    expect(keyExpiry('2026-12-13T12:00:00Z', now)).toBe('2026-12-13T12:00:00.000Z');
  });
  it('refuses none, a past time and garbage', () => {
    for (const v of [undefined, null, '', 'soon', 42, '2026-11-13T11:59:59Z']) {
      expect(keyExpiry(v, now)).toBeNull();
    }
  });
});
