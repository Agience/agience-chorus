import { describe, expect, it } from 'vitest';
import { workspaceLabel, workspaceLabels } from '../workspaceLabels';

const NOW = new Date('2026-11-14T20:00:00');

describe('workspaceLabels: same-name workspaces can be told apart', () => {
  it('lists a workspace Mantle leaves unmarked by the name alone', () => {
    const labels = workspaceLabels([
      { id: 'a', name: 'Research', created_time: '2026-11-01T10:00:00' },
      { id: 'b', name: 'Pilot', created_time: '2026-11-02T10:00:00' },
    ], NOW);
    expect(labels.get('a')).toBe('Research');
    expect(labels.get('b')).toBe('Pilot');
  });

  it('adds the day made where Mantle marks the day', () => {
    expect(workspaceLabel({ id: 'a', name: 'Notes', created_time: '2026-11-01T10:00:00', label_at: 'day' }, NOW))
      .toBe('Notes · 1 Nov');
  });

  it('adds the time, or the seconds, where Mantle marks them', () => {
    expect(workspaceLabel({ id: 'a', name: 'Notes', created_time: '2026-11-14T09:05:00', label_at: 'minute' }, NOW))
      .toMatch(/^Notes · 14 Nov \d{2}:\d{2}$/);
    expect(workspaceLabel({ id: 'b', name: 'Notes', created_time: '2026-11-14T20:16:41', label_at: 'second' }, NOW))
      .toMatch(/41/);
    expect(workspaceLabel({ id: 'c', name: 'Notes', created_time: '2025-03-02T12:00:00', label_at: 'day' }, NOW))
      .toMatch(/2025/);
  });

  it('adds the number Mantle gives', () => {
    expect(workspaceLabel({ id: 'y', name: 'Draft', label_n: 2 }, NOW)).toBe('Draft (2)');
  });
});
