// 2026-10-31, a tester: with mixed memberships the bulk picker showed every box unchecked, so a
// collection some of the selection belongs to looked the same as one none of it does.
import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

vi.mock('../../../api/collections', () => ({
  listCollections: async (_action?: string, contentType?: string) => contentType?.includes('workspace') ? [] : [
    { id: 'c-all', name: 'All of them', created_time: '2026-10-01T00:00:00Z' },
    { id: 'c-some', name: 'Some of them', created_time: '2026-10-01T00:00:00Z' },
    { id: 'c-none', name: 'None of them', created_time: '2026-10-01T00:00:00Z' },
  ],
  createCollection: vi.fn(),
}));
vi.mock('../../../hooks/useWorkspaces', () => ({ useWorkspaces: () => ({ activeWorkspaceId: 'ws-1' }) }));
vi.mock('react-hot-toast', () => ({ default: { success: vi.fn(), error: vi.fn() } }));
vi.mock('../../../context/auth/AuthContext', async () => { const { createContext } = await import('react'); return { AuthContext: createContext({ user: { id: 'me' } }) }; });

import { CollectionPicker } from '../CollectionPicker';

function row(name: string) {
  return screen.getByText(name).closest('button') as HTMLButtonElement;
}

function open(onSelect = vi.fn()) {
  render(
    <CollectionPicker open onClose={() => {}} onSelect={onSelect} multiple
      selectedCollectionIds={['c-all']} partialCollectionIds={['c-some']} />,
  );
  return onSelect;
}

describe('The bulk collection picker', () => {
  it('shows all, some and none as three states', async () => {
    open();
    await waitFor(() => expect(screen.getByText('Some of them')).toBeTruthy());
    expect(row('All of them').dataset.membership).toBe('all');
    expect(row('Some of them').dataset.membership).toBe('some');
    expect(row('None of them').dataset.membership).toBe('none');
  });

  it('leaves a mixed collection alone unless it is changed', async () => {
    const onSelect = open();
    await waitFor(() => expect(screen.getByText('Some of them')).toBeTruthy());
    await userEvent.setup().click(screen.getByRole('button', { name: /select/i }));
    expect(onSelect).toHaveBeenCalledWith(['c-all'], []);
  });

  it('cycles a mixed collection through all, none and back to some', async () => {
    const user = userEvent.setup();
    const onSelect = open();
    await waitFor(() => expect(screen.getByText('Some of them')).toBeTruthy());
    await user.click(row('Some of them'));
    expect(row('Some of them').dataset.membership).toBe('all');
    await user.click(row('Some of them'));
    expect(row('Some of them').dataset.membership).toBe('none');
    await user.click(screen.getByRole('button', { name: /select/i }));
    expect(onSelect).toHaveBeenCalledWith(['c-all'], ['c-some']);
  });
});
