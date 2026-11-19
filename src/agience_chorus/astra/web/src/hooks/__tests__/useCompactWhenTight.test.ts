import { describe, expect, it } from 'vitest';
import { nextCompact } from '../useCompactWhenTight';

describe('nextCompact', () => {
  it('keeps labels while the content fits', () => {
    expect(nextCompact(false, 500, 600, 0)).toBe(false);
    expect(nextCompact(false, 600, 600, 0)).toBe(false);
  });

  it('drops labels once the content is wider than its room', () => {
    expect(nextCompact(false, 601, 600, 0)).toBe(true);
  });

  it('brings labels back only when the room left over holds them', () => {
    // Compact, the room is 700 and the content 600: 100 px spare, the labels need 150.
    expect(nextCompact(true, 600, 700, 150)).toBe(true);
    expect(nextCompact(true, 600, 750, 150)).toBe(false);
  });

  it('settles at one width: a row that just compacted stays compact', () => {
    // At full width the room is 600 for 650 of content; dropping 150 px of labels gives 750.
    const compact = nextCompact(false, 650, 600, 0);
    expect(compact).toBe(true);
    expect(nextCompact(compact, 650, 750, 150)).toBe(true);
  });
});
