import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import FilterBar from '../FilterBar';

const props = {
  counts: { total: 0, archived: 0 },
  activeFilter: 'all' as const,
  onFilterChange: () => {},
  sortBy: 'manual' as const,
  onSortChange: () => {},
  viewMode: 'grid' as const,
  onViewChange: () => {},
};

describe('FilterBar drawer', () => {
  it('a closed drawer offers no controls', () => {
    render(<FilterBar {...props} isOpen={false} />);
    const bar = screen.getByTestId('filter-bar');
    expect(bar).toHaveAttribute('inert');
    expect(bar).toHaveAttribute('aria-hidden', 'true');
    expect(bar.className).toContain('invisible');
    expect(screen.queryByRole('button', { name: /Sort:/ })).toBeNull();
  });

  it('an open drawer offers Sort and View', () => {
    render(<FilterBar {...props} isOpen />);
    const bar = screen.getByTestId('filter-bar');
    expect(bar).not.toHaveAttribute('inert');
    expect(screen.getByRole('button', { name: /Sort: Manual order/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /View: Grid/ })).toBeInTheDocument();
  });
});
