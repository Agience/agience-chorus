import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

// 2026-11-15, the Tester: the Key artifact's picker offered collections the person could not grant,
// and Origin then refused the key. A view may ask for only what the person may do a given thing to.
const listCollections = vi.fn();
vi.mock('../../../api/collections', () => ({
  listCollections: (...a: unknown[]) => listCollections(...a),
  listVisibleOfType: vi.fn().mockResolvedValue([]),
}));
vi.mock('react-hot-toast', () => ({ default: { error: vi.fn() } }));

import { BindingPicker } from '../BindingPicker';

describe('BindingPicker, by action', () => {
  beforeEach(() => {
    listCollections.mockReset().mockResolvedValue([{ id: 'c1', name: 'Pilot notes' }]);
  });

  it('lists only what the person may grant when asked for admin', async () => {
    render(<BindingPicker open onClose={() => {}} onSelect={() => {}} action="admin" />);
    await waitFor(() => expect(screen.getByText('Pilot notes')).toBeDefined());
    expect(listCollections).toHaveBeenCalledWith('admin');
  });

  it('lists everything readable when asked for nothing in particular', async () => {
    render(<BindingPicker open onClose={() => {}} onSelect={() => {}} />);
    await waitFor(() => expect(listCollections).toHaveBeenCalledWith('read'));
  });
});
