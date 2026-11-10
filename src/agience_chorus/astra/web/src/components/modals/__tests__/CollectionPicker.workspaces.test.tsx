// BUG-014 (2026-11-10): Assign to Collections could not target a workspace, so an artifact could not
// be placed into a workspace shared with the person. Workspaces they may add to are offered too.
import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const listCollections = vi.fn(async (_action?: string, contentType?: string) =>
  contentType?.includes('workspace')
    ? [{ id: 'ws-agency', name: 'Agience', created_by: 'agency', created_time: '2026-11-01T00:00:00Z' },
       { id: 'ws-mine', name: 'Agience', created_by: 'me', created_time: '2026-11-01T00:00:00Z' }]
    : [{ id: 'c-1', name: 'Notes', created_time: '2026-11-01T00:00:00Z' }]);
vi.mock('../../../api/collections', () => ({
  listCollections: (...a: [string?, string?]) => listCollections(...a),
  createCollection: vi.fn(),
}));
vi.mock('../../../hooks/useWorkspaces', () => ({ useWorkspaces: () => ({ activeWorkspaceId: 'ws-1' }) }));
vi.mock('react-hot-toast', () => ({ default: { success: vi.fn(), error: vi.fn() } }));
vi.mock('../../../context/auth/AuthContext', async () => { const { createContext } = await import('react'); return { AuthContext: createContext({ user: { id: 'me' } }) }; });

import { CollectionPicker } from '../CollectionPicker';

describe('Assign to Collections', () => {
  it('offers the workspaces the person may add to, marked as workspaces, and assigns into one', async () => {
    const onSelect = vi.fn();
    render(<CollectionPicker open onClose={() => {}} onSelect={onSelect} multiple selectedCollectionIds={[]} />);
    await waitFor(() => expect(screen.getAllByText('Agience').length).toBe(2));
    expect(listCollections).toHaveBeenCalledWith('create', 'application/vnd.agience.workspace+json');
    // Two of one name are told apart by whose they are (BUG-042).
    const [row, mine] = screen.getAllByText('Agience').map(e => e.closest('button') as HTMLButtonElement);
    expect(row.textContent).toContain('Workspace · shared with you');
    expect(mine.textContent).toContain('Workspace');
    expect(mine.textContent).not.toContain('shared with you');
    expect((screen.getByText('Notes').closest('button') as HTMLButtonElement).textContent).not.toContain('Workspace');
    const user = userEvent.setup();
    await user.click(row);
    await user.click(screen.getByRole('button', { name: /select/i }));
    expect(onSelect).toHaveBeenCalledWith(['ws-agency'], []);
  });
});
