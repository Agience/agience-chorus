import { describe, expect, it } from 'vitest';
import { formatClock, formatDay, formatDayTime } from '../dates';

describe('dates', () => {
  const when = new Date(2026, 10, 15, 14, 5, 9);

  it('shows a day first, the month as a word', () => {
    expect(formatDay(when)).toBe('15 Nov 2026');
    expect(formatDay('2026-03-02T12:00:00')).toBe('2 Mar 2026');
  });

  it('drops the year inside the current year when asked', () => {
    expect(formatDay(when, new Date(2026, 0, 1))).toBe('15 Nov');
    expect(formatDay(when, new Date(2027, 0, 1))).toBe('15 Nov 2026');
  });

  it('shows times on a 24-hour clock', () => {
    expect(formatClock(when)).toBe('14:05');
    expect(formatClock(when, true)).toBe('14:05:09');
    expect(formatDayTime(when)).toBe('15 Nov 2026, 14:05');
  });

  it('shows nothing for no date or a bad one', () => {
    expect(formatDay(undefined)).toBe('');
    expect(formatDay('not a date')).toBe('');
    expect(formatDayTime(null)).toBe('');
  });
});
