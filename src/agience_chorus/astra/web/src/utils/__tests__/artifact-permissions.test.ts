import { describe, expect, it } from 'vitest';

import { allows } from '../artifact-permissions';

describe('allows', () => {
  it('offers what Mantle answered', () => {
    expect(allows({ allowed_actions: ['read', 'delete'] }, 'delete')).toBe(true);
    expect(allows({ allowed_actions: ['read'] }, 'delete')).toBe(false);
  });

  it('offers nothing without an answer', () => {
    expect(allows({}, 'delete')).toBe(false);
    expect(allows(null, 'read')).toBe(false);
  });
});
