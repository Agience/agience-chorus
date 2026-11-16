import { describe, expect, it } from 'vitest';
import { UNTITLED_WORKSPACE, workspaceLabels } from '../workspaceLabels';

const NOW = new Date('2026-11-14T20:00:00');

describe('workspaceLabels (BUG-001: same-name workspaces can be told apart)', () => {
  it('lists a workspace whose name is its own by the name alone', () => {
    const labels = workspaceLabels([
      { id: 'a', name: 'Research', created_time: '2026-11-01T10:00:00' },
      { id: 'b', name: 'Pilot', created_time: '2026-11-02T10:00:00' },
    ], NOW);
    expect(labels.get('a')).toBe('Research');
    expect(labels.get('b')).toBe('Pilot');
  });

  it('adds the day made where two share a name', () => {
    const labels = workspaceLabels([
      { id: 'a', name: 'Untitled Workspace', created_time: '2026-11-01T10:00:00' },
      { id: 'b', name: 'untitled workspace', created_time: '2026-11-03T10:00:00' },
    ], NOW);
    expect(labels.get('a')).toMatch(/^Untitled Workspace · Nov\.? 1$/);
    expect(labels.get('b')).toMatch(/^untitled workspace · Nov\.? 3$/);
    expect(labels.get('a')).not.toBe(labels.get('b'));
  });

  it('adds the time where they were made the same day, and the year when not this year', () => {
    const labels = workspaceLabels([
      { id: 'a', name: 'Notes', created_time: '2026-11-14T09:05:00' },
      { id: 'b', name: 'Notes', created_time: '2026-11-14T16:40:00' },
      { id: 'c', name: 'Notes', created_time: '2025-03-02T12:00:00' },
    ], NOW);
    expect(new Set(labels.values()).size).toBe(3);
    expect(labels.get('a')).toMatch(/Nov\.? 14 \d{2}:\d{2}/);
    expect(labels.get('c')).toMatch(/2025/);
  });

  it('adds the seconds where two were made in the same minute (the Tester, 2026-11-15)', () => {
    const labels = workspaceLabels([
      { id: 'a', name: 'Notes', created_time: '2026-11-14T20:16:05' },
      { id: 'b', name: 'Notes', created_time: '2026-11-14T20:16:41' },
    ], NOW);
    expect(labels.get('a')).not.toBe(labels.get('b'));
    expect(labels.get('a')).toMatch(/05/);
    expect(labels.get('b')).toMatch(/41/);
  });

  it('numbers them, in the order made, where even the second is the same, or there is no time', () => {
    const labels = workspaceLabels([
      { id: 'b', name: 'Notes', created_time: '2026-11-14T20:16:05.900Z' },
      { id: 'a', name: 'Notes', created_time: '2026-11-14T20:16:05.100Z' },
      { id: 'x', name: 'Draft' },
      { id: 'y', name: 'Draft' },
    ], NOW);
    expect(labels.get('b')).toBe(`${labels.get('a')} (2)`);
    expect(labels.get('x')).toBe('Draft');
    expect(labels.get('y')).toBe('Draft (2)');
  });

  it('names a blank workspace Untitled workspace', () => {
    const labels = workspaceLabels([{ id: 'a', name: '  ' }], NOW);
    expect(labels.get('a')).toBe(UNTITLED_WORKSPACE);
  });
});
