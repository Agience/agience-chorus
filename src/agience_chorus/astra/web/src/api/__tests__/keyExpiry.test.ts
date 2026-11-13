import { describe, expect, it } from 'vitest';

import { keyExpiry } from '../apiKeys';

// FR-019 (John, 2026-11-13): every key a view asks for expires, within a year.
describe('keyExpiry', () => {
  const now = Date.parse('2026-11-13T12:00:00Z');
  it('takes a time ahead and within a year, as ISO', () => {
    expect(keyExpiry('2026-12-13T12:00:00Z', now)).toBe('2026-12-13T12:00:00.000Z');
  });
  it('refuses none, a past time, garbage, and more than a year', () => {
    for (const v of [undefined, null, '', 'soon', 42, '2026-11-13T11:59:59Z', '2027-11-15T12:00:00Z']) {
      expect(keyExpiry(v, now)).toBeNull();
    }
  });
});
