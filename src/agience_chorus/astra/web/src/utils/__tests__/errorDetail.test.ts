import { describe, expect, it } from 'vitest';

import { errorDetail } from '../errorDetail';

const axiosLike = (detail: unknown) => ({ response: { data: { detail } } });

describe('errorDetail', () => {
  it('returns a string detail', () => {
    expect(errorDetail(axiosLike('Workspace limit reached'), 'fallback')).toBe('Workspace limit reached');
  });

  it('joins validation messages', () => {
    expect(errorDetail(axiosLike([{ msg: 'name required' }, { msg: 'too long' }]), 'fallback')).toBe('name required; too long');
  });

  it('reads a structured detail message', () => {
    expect(errorDetail(axiosLike({ code: 'x', message: 'Refused' }), 'fallback')).toBe('Refused');
  });

  it('falls back when there is no response', () => {
    expect(errorDetail(new Error('Network Error'), 'fallback')).toBe('fallback');
    expect(errorDetail(axiosLike(''), 'fallback')).toBe('fallback');
    expect(errorDetail(axiosLike({ code: 'x' }), 'fallback')).toBe('fallback');
  });
});
