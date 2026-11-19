import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import { SearchPanel } from '../SearchPanel';
import type { SearchResponse } from '../../../api/types/search';

vi.mock('../../browser/AdvancedSearch', () => ({
  default: (props: { onResults?: (r: SearchResponse) => void; onClear?: () => void }) => (
    <div>
      <button type="button" onClick={() => props.onResults?.({ hits: [], total: 0, query_text: 'pilot plan', from: 0, size: 100 })}>
        search
      </button>
      <button type="button" onClick={() => props.onClear?.()}>clear</button>
    </div>
  ),
}));

describe('SearchPanel empty state', () => {
  it('names what was searched and where when nothing matches, and forgets it on clear', () => {
    render(<SearchPanel artifacts={[]} />);
    expect(screen.getByText('Nothing here yet')).toBeTruthy();

    fireEvent.click(screen.getByText('search'));
    expect(screen.getByText('No matches')).toBeTruthy();
    expect(screen.getByText('Nothing in your workspaces and collections matches "pilot plan".')).toBeTruthy();

    fireEvent.click(screen.getByText('clear'));
    expect(screen.queryByText('No matches')).toBeNull();
    expect(screen.getByText('Nothing here yet')).toBeTruthy();
  });
});
