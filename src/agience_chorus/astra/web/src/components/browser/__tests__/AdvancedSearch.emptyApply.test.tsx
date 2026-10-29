import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

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
  // 2026-10-23, a tester applied a tag filter with the box empty: no request, and no word why.
  it('keeps the panel open and says a word is needed', () => {
    render(<AdvancedSearch scope="global" scopeId="" enableSuggestions={false} compact />);
    fireEvent.click(screen.getByTitle('Advanced search filters'));
    fireEvent.change(screen.getByLabelText('Has tag'), { target: { value: 'beta-test' } });
    fireEvent.click(screen.getByText('Apply filters'));

    expect(screen.getByText('Apply filters')).toBeInTheDocument();
    expect(screen.getAllByRole('status').some((n) => /add a word to search for/i.test(n.textContent ?? ''))).toBe(true);
    expect(searchGlobalMock).not.toHaveBeenCalled();
  });
});
