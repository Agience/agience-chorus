import { describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';

import AdvancedSearch from '../AdvancedSearch';

const { searchGlobalMock } = vi.hoisted(() => ({ searchGlobalMock: vi.fn() }));

vi.mock('../../../api/search', () => ({
  searchGlobal: (...a: unknown[]) => searchGlobalMock(...a),
  searchWorkspace: vi.fn(),
  searchCollection: vi.fn(),
  getWorkspaceSuggestions: vi.fn(() => Promise.resolve({ tags: [], titles: [] })),
  getCollectionSuggestions: vi.fn(() => Promise.resolve({ tags: [], titles: [] })),
}));

vi.mock('@/context/shortcuts/useShortcuts', () => ({
  useShortcuts: () => ({ registerShortcut: () => () => {} }),
}));

describe('AdvancedSearch Apply with no search text', () => {
  // Mantle refuses a search of filters alone; the panel stays open and says Mantle's reason.
  it('keeps the panel open and says the reason Mantle refused it', async () => {
    const reason = 'Add a word to search for: tag: narrows a search, it is not one.';
    searchGlobalMock.mockRejectedValue({ response: { status: 400, data: { detail: reason } } });
    render(<AdvancedSearch scope="global" scopeId="" enableSuggestions={false} compact />);
    fireEvent.click(screen.getByTitle('Advanced search filters'));
    fireEvent.change(screen.getByLabelText('Has tag'), { target: { value: 'beta-test' } });
    await act(async () => { fireEvent.click(screen.getByText('Apply filters')); });

    expect(screen.getByText('Apply filters')).toBeInTheDocument();
    expect(screen.getAllByRole('status').some((n) => (n.textContent ?? '').includes(reason))).toBe(true);
    expect(searchGlobalMock.mock.calls[0][0]).toMatchObject({ query_text: '', tag: 'beta-test' });
  });
});
