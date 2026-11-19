import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

// 2026-11-15, the Tester: the Key artifact's picker offered collections the person could not grant,
// and Origin then refused the key. A view may ask for only what the person may do a given thing to.
const listCollections = vi.fn();
const listVisibleOfTypes = vi.fn();
vi.mock('../../../api/collections', () => ({
  listCollections: (...a: unknown[]) => listCollections(...a),
  listVisibleOfTypes: (...a: unknown[]) => listVisibleOfTypes(...a),
}));
vi.mock('react-hot-toast', () => ({ default: { error: vi.fn() } }));

import { BindingPicker } from '../BindingPicker';

describe('BindingPicker, by action', () => {
  beforeEach(() => {
    listCollections.mockReset().mockResolvedValue([{ id: 'c1', name: 'Pilot notes' }]);
    listVisibleOfTypes.mockReset().mockResolvedValue([
      { id: 'w1', name: 'Plans' }, { id: 'n1', name: 'Notes' }]);
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

  it('asks Mantle once for every type it may offer, and shows each choice as Mantle names it', async () => {
    render(<BindingPicker open onClose={() => {}} onSelect={() => {}}
      contentTypes={['application/a+json', 'application/b+json']} action="update" />);
    await waitFor(() => expect(screen.getByText('Plans')).toBeDefined());
    expect(screen.getByText('Notes')).toBeDefined();
    expect(listVisibleOfTypes).toHaveBeenCalledTimes(1);
    expect(listVisibleOfTypes).toHaveBeenCalledWith(['application/a+json', 'application/b+json'], 'update');
    expect(listCollections).not.toHaveBeenCalled();
  });
});
