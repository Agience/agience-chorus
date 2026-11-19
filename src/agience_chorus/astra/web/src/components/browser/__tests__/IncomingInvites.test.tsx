import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// FR-004: an invite to someone with an account arrives in their Inbox as an invite artifact, with
// Accept and Decline, so accepting it needs no email. Both are taken in the person's Origin
// session, at the path the invite's type names.
const incomingMock = vi.fn();
const actMock = vi.fn();
vi.mock('@/api/inviteArtifacts', () => ({
  offeredInvites: (...a: unknown[]) => incomingMock(...a),
  actOnInvite: (...a: unknown[]) => actMock(...a),
}));
const toastSuccess = vi.fn();
const toastError = vi.fn();
vi.mock('sonner', () => ({ toast: { success: (...a: unknown[]) => toastSuccess(...a),
                                    error: (...a: unknown[]) => toastError(...a),
                                    loading: vi.fn(() => 'joining'), dismiss: vi.fn(),
                                    info: vi.fn() } }));
// Mantle's role presets, which name each invite's actions.
vi.mock('@/api/collections', async (orig) => ({
  ...(await orig<typeof import('@/api/collections')>()),
  listRoles: vi.fn().mockResolvedValue([
    { name: 'viewer', actions: ['read'] },
    { name: 'editor', actions: ['create', 'read', 'update', 'delete'] },
  ]),
}));
// The store answers at once here, so Accept opens the item.
vi.mock('@/api/artifacts', () => ({ getArtifact: vi.fn().mockResolvedValue({ id: 'W' }) }));
const assign = vi.fn();
Object.defineProperty(window, 'location', { value: { ...window.location, assign }, writable: true });

import { IncomingInvites } from '../IncomingInvites';

const INV = { id: 'a1', invite_id: 'inv-1', resource_id: 'W', resource_name: 'Plans',
              actions: ['read'], expires_at: null, from: 'ann' };

describe('IncomingInvites — invites arrive in the Inbox', () => {
  beforeEach(() => {
    incomingMock.mockReset();
    actMock.mockReset();
    toastSuccess.mockReset();
    toastError.mockReset();
  });

  it('names what is shared and the role, and accepts the invite artifact', async () => {
    incomingMock.mockResolvedValueOnce([INV]).mockResolvedValueOnce([]);
    actMock.mockResolvedValue({ grant_id: 'claim-1' });
    render(<IncomingInvites />);
    await waitFor(() => expect(screen.getByText('Plans')).toBeTruthy());
    await waitFor(() => expect(screen.getByText(/as Viewer/)).toBeTruthy());
    fireEvent.click(screen.getByText('Accept'));
    await waitFor(() => expect(actMock).toHaveBeenCalledWith('a1', 'accept'));
    await waitFor(() => expect(screen.queryByText('Plans')).toBeNull());
    expect(toastSuccess).toHaveBeenCalled();
    expect(assign).toHaveBeenCalledWith('/W');
    expect(actMock).toHaveBeenCalledTimes(1);
  });

  it('declines the invite artifact', async () => {
    incomingMock.mockResolvedValueOnce([INV]).mockResolvedValueOnce([]);
    actMock.mockResolvedValue({});
    render(<IncomingInvites />);
    await waitFor(() => expect(screen.getByText('Decline')).toBeTruthy());
    fireEvent.click(screen.getByText('Decline'));
    await waitFor(() => expect(actMock).toHaveBeenCalledWith('a1', 'decline'));
    expect(actMock).toHaveBeenCalledTimes(1);
  });

  it('shows nothing when there are no invites, or they cannot be listed', async () => {
    incomingMock.mockRejectedValue(new Error('401'));
    const { container } = render(<IncomingInvites />);
    await waitFor(() => expect(incomingMock).toHaveBeenCalled());
    expect(container.textContent).toBe('');
  });

  it('a refused accept says so and keeps the invite listed', async () => {
    incomingMock.mockResolvedValue([INV]);
    actMock.mockRejectedValue(new Error('this invite does not name you'));
    render(<IncomingInvites />);
    await waitFor(() => expect(screen.getByText('Accept')).toBeTruthy());
    fireEvent.click(screen.getByText('Accept'));
    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(screen.getByText('Plans')).toBeTruthy();
  });

  it('names the Mantle role whose actions an invite holds exactly, else lists the actions', async () => {
    incomingMock.mockResolvedValue([
      { ...INV, id: 'a2', invite_id: 'inv-2', actions: ['delete', 'update', 'read', 'create'] },
      { ...INV, id: 'a3', invite_id: 'inv-3', actions: ['read', 'invoke'] },
    ]);
    render(<IncomingInvites />);
    await waitFor(() => expect(screen.getByText(/as Editor/)).toBeTruthy());
    expect(screen.getByText(/as read, invoke/)).toBeTruthy();
  });
});

// After Accept the grant reaches the store a few seconds later (2026-11-13, the Tester): Accept
// waits for it, then opens the item; past the wait it says access is on its way, never "not shared".
import { waitForAccess } from '../invites';

describe('waitForAccess', () => {
  const noSleep = () => Promise.resolve();

  it('opens as soon as the store lets the person read it', async () => {
    const read = vi.fn().mockRejectedValueOnce(new Error('403')).mockRejectedValueOnce(new Error('403'))
      .mockResolvedValue({ id: 'W' });
    await expect(waitForAccess('W', 20000, 1000, read, noSleep)).resolves.toBe(true);
    expect(read).toHaveBeenCalledTimes(3);
  });

  it('gives up after the wait, without throwing', async () => {
    const read = vi.fn().mockRejectedValue(new Error('403'));
    await expect(waitForAccess('W', 5000, 1000, read, noSleep)).resolves.toBe(false);
    expect(read).toHaveBeenCalledTimes(5);
  });
});
