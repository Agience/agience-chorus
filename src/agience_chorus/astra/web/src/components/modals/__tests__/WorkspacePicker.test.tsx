import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';

import WorkspacePicker from '../WorkspacePicker';

const WORKSPACES = [
  { id: 'a', name: 'Research', created_time: '2026-11-01T10:00:00' },
  { id: 'b', name: 'Untitled workspace', created_time: '2026-11-02T10:00:00' },
  { id: 'c', name: 'Untitled workspace', created_time: '2026-11-03T10:00:00' },
];

describe('WorkspacePicker (BUG-075: Add to workspace asks where)', () => {
  it('lists the open workspace first, tells same-name ones apart, and picks the one clicked', () => {
    const onPick = vi.fn();
    render(<WorkspacePicker open title="Add to workspace" workspaces={WORKSPACES} currentId="c"
      onPick={onPick} onClose={() => {}} />);
    const items = within(screen.getByRole('list', { name: 'Workspaces' })).getAllByRole('button');
    expect(items).toHaveLength(3);
    expect(items[0].textContent).toMatch(/^Untitled workspace · Nov\.? 3open now$/);
    expect(new Set(items.map((i) => i.textContent)).size).toBe(3);
    fireEvent.click(screen.getByRole('button', { name: /Research/ }));
    expect(onPick).toHaveBeenCalledWith('a');
  });
});
