import { describe, it, expect } from 'vitest';
import { nextUntitledTitle } from '../untitled';

describe('nextUntitledTitle', () => {
  it('takes the base when it is free, else the first free number', () => {
    expect(nextUntitledTitle('Untitled Search', [])).toBe('Untitled Search');
    expect(nextUntitledTitle('Untitled Search', ['Untitled Search'])).toBe('Untitled Search 2');
    expect(nextUntitledTitle('Untitled Search', ['Untitled Search', 'Untitled Search 3'])).toBe('Untitled Search 2');
    expect(nextUntitledTitle('Untitled Search', ['Untitled Search 2'])).toBe('Untitled Search');
    expect(nextUntitledTitle('Untitled Search', ['Untitled Searches', 'Other'])).toBe('Untitled Search');
  });
});

describe('titleOrFallback', () => {
  it('keeps a typed title', async () => {
    const { titleOrFallback } = await import('../untitled');
    expect(titleOrFallback(' Plan ', '# Heading', 'Old')).toBe('Plan');
  });
  it('falls back to the first line of the content, then the previous title', async () => {
    const { titleOrFallback } = await import('../untitled');
    expect(titleOrFallback('  ', '\n# Q4 plan\nmore', 'Old')).toBe('Q4 plan');
    expect(titleOrFallback('', '', 'Old')).toBe('Old');
    expect(titleOrFallback('', '', '')).toBe('Untitled');
  });
});
