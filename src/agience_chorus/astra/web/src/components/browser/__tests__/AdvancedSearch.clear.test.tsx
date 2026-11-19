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

const empty: { hits: { id: string }[]; total: number; query_text: string; from: number; size: number } = {
  hits: [], total: 0, query_text: '', from: 0, size: 20,
};

function searchExactly(term: string) {
  fireEvent.change(screen.getByPlaceholderText(/search/i), { target: { value: term } });
  fireEvent.click(screen.getByTitle('Advanced search filters'));
  fireEvent.click(screen.getByDisplayValue('exact'));
  fireEvent.click(screen.getByText('Apply filters'));
}

describe('AdvancedSearch Clear', () => {
  it('leaves no line naming the search it cleared', async () => {
    searchGlobalMock.mockResolvedValue({ ...empty, query_text: '="budget"' });
    render(<AdvancedSearch scope="global" scopeId="" enableSuggestions={false} compact />);
    searchExactly('budget');
    await act(async () => {});
    expect(screen.getByTestId('sent-query')).toHaveTextContent('="budget"');

    fireEvent.click(screen.getByTitle('Clear (Esc)'));
    expect(screen.queryByTestId('sent-query')).not.toBeInTheDocument();
  });

  it('drops the answer of a search still in flight when the box is cleared', async () => {
    let answer: (v: typeof empty) => void = () => {};
    searchGlobalMock.mockReturnValue(new Promise((r) => { answer = r; }));
    const onResults = vi.fn();
    render(<AdvancedSearch scope="global" scopeId="" enableSuggestions={false} compact onResults={onResults} />);
    searchExactly('budget');

    fireEvent.click(screen.getByTitle('Clear (Esc)'));
    onResults.mockClear();
    await act(async () => { answer({ ...empty, hits: [{ id: 'a1' }] }); });
    expect(onResults).not.toHaveBeenCalled();
  });
});
