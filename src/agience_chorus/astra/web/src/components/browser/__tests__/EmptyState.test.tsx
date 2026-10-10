import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import EmptyState from '../EmptyState';
import { EMPTY_STATE } from '@/constants/strings';

describe('EmptyState', () => {
  it.each(['no-artifacts', 'no-source'] as const)('%s renders both create actions and wires them', (type) => {
    const onCreateWorkspace = vi.fn();
    const onCreateCard = vi.fn();
    render(<EmptyState type={type} onCreateWorkspace={onCreateWorkspace} onCreateCard={onCreateCard} />);

    fireEvent.click(screen.getByRole('button', { name: EMPTY_STATE.NEW_CARD }));
    fireEvent.click(screen.getByRole('button', { name: EMPTY_STATE.CREATE_WORKSPACE }));

    expect(onCreateCard).toHaveBeenCalledTimes(1);
    expect(onCreateWorkspace).toHaveBeenCalledTimes(1);
  });

  it.each(['no-artifacts', 'no-source'] as const)('%s renders no buttons without handlers', (type) => {
    render(<EmptyState type={type} />);
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('tells an Inbox user they can create a card right here', () => {
    render(<EmptyState type="no-artifacts" isInbox onCreateCard={() => {}} />);
    expect(screen.getByText(EMPTY_STATE.NO_ARTIFACTS_INBOX_BODY)).toBeInTheDocument();
  });

  it('offers no create actions for search results, only clearing the search', () => {
    const onClearSearch = vi.fn();
    render(
      <EmptyState
        type="no-search-results"
        searchQuery="zzz"
        onClearSearch={onClearSearch}
        onCreateWorkspace={() => {}}
        onCreateCard={() => {}}
      />,
    );

    expect(screen.queryByRole('button', { name: EMPTY_STATE.NEW_CARD })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: EMPTY_STATE.CLEAR_SEARCH }));
    expect(onClearSearch).toHaveBeenCalledTimes(1);
  });

  it('offers Clear filters when filters, not search text, hide every card', () => {
    const onClearFilters = vi.fn();
    render(<EmptyState type="no-search-results" onClearFilters={onClearFilters} />);

    expect(screen.getByText(EMPTY_STATE.NO_FILTER_RESULTS_BODY)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: EMPTY_STATE.CLEAR_SEARCH })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: EMPTY_STATE.CLEAR_FILTERS }));
    expect(onClearFilters).toHaveBeenCalledTimes(1);
  });
});
