// The filters panel renders in the top layer, outside the search box's own tree, so a narrow
// sidebar or a scrolling panel never clips it; the toggle still opens and closes it.
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import AdvancedSearch from '../AdvancedSearch';

vi.mock('../../../api/search', () => ({
  searchGlobal: vi.fn(),
  searchWorkspace: vi.fn(),
  searchCollection: vi.fn(),
  getWorkspaceSuggestions: vi.fn(() => Promise.resolve({ tags: [], titles: [] })),
  getCollectionSuggestions: vi.fn(() => Promise.resolve({ tags: [], titles: [] })),
}));

vi.mock('@/context/shortcuts/useShortcuts', () => ({
  useShortcuts: () => ({ registerShortcut: () => () => {} }),
}));

describe('The search filters panel', () => {
  it('opens in a portal and closes from its toggle', () => {
    const { container } = render(
      <div style={{ overflow: 'hidden' }}>
        <AdvancedSearch scope="global" scopeId="" enableSuggestions={false} compact />
      </div>,
    );
    const toggle = screen.getByTitle('Advanced search filters');
    fireEvent.click(toggle);
    const apply = screen.getByText('Apply filters');
    expect(container.contains(apply)).toBe(false);
    expect(document.body.contains(apply)).toBe(true);

    fireEvent.click(toggle);
    expect(screen.queryByText('Apply filters')).toBeNull();
  });

  it('closes on Escape', () => {
    render(<AdvancedSearch scope="global" scopeId="" enableSuggestions={false} compact />);
    fireEvent.click(screen.getByTitle('Advanced search filters'));
    fireEvent.keyDown(screen.getByLabelText('Has tag'), { key: 'Escape' });
    expect(screen.queryByText('Apply filters')).toBeNull();
  });
});
