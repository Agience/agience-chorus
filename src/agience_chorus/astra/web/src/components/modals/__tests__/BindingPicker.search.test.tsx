import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const listCollections = vi.fn();
const searchChoices = vi.fn();
vi.mock('../../../api/collections', () => ({
  listCollections: (...a: unknown[]) => listCollections(...a),
  listVisibleOfTypes: vi.fn(),
}));
vi.mock('@/api/search', () => ({ searchChoices: (...a: unknown[]) => searchChoices(...a) }));
vi.mock('react-hot-toast', () => ({ default: { error: vi.fn() } }));

import { BindingPicker } from '../BindingPicker';

describe('BindingPicker search', () => {
  beforeEach(() => {
    listCollections.mockReset().mockResolvedValue([
      { id: 'a', name: 'Alpha' }, { id: 'b', name: 'Beta' }, { id: 'c', name: 'Gamma' }]);
    searchChoices.mockReset().mockResolvedValue(['c', 'x', 'a']);
  });

  it('runs the platform Search and shows what it finds among the listed, in its order', async () => {
    const user = userEvent.setup();
    render(<BindingPicker open onClose={() => {}} onSelect={() => {}} />);
    await waitFor(() => expect(screen.getByText('Beta')).toBeDefined());
    await user.type(screen.getByRole('textbox'), 'plans');
    await waitFor(() => expect(screen.queryByText('Beta')).toBeNull());
    expect(searchChoices).toHaveBeenLastCalledWith('plans', ['application/vnd.agience.collection+json']);
    const shown = screen.getAllByText(/Alpha|Gamma/).map((n) => n.textContent);
    expect(shown).toEqual(['Gamma', 'Alpha']);
  });
});
