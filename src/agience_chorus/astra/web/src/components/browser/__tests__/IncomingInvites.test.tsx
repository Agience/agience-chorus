import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// FR-004: an invite to someone with an account arrives in their Inbox, with Accept and Decline,
// so accepting it needs no email. Both are made at Origin in the person's Origin session.
const incomingMock = vi.fn();
const acceptMock = vi.fn();
const declineMock = vi.fn();
vi.mock('@/api/authority', () => ({
  incomingInvites: (...a: unknown[]) => incomingMock(...a),
  acceptInvite: (...a: unknown[]) => acceptMock(...a),
  declineInvite: (...a: unknown[]) => declineMock(...a),
}));
const toastSuccess = vi.fn();
const toastError = vi.fn();
vi.mock('sonner', () => ({ toast: { success: (...a: unknown[]) => toastSuccess(...a),
                                    error: (...a: unknown[]) => toastError(...a),
                                    loading: vi.fn(() => 'joining'), dismiss: vi.fn(),
                                    info: vi.fn() } }));
// The store answers at once here, so Accept opens the item.
vi.mock('@/api/artifacts', () => ({ getArtifact: vi.fn().mockResolvedValue({ id: 'W' }) }));
const assign = vi.fn();
Object.defineProperty(window, 'location', { value: { ...window.location, assign }, writable: true });

import { IncomingInvites, roleOf } from '../IncomingInvites';

const INV = { invite_id: 'inv-1', resource_id: 'W', actions: ['read'], expires_at: null,
              from: 'Ann Lee' };

describe('IncomingInvites — invites arrive in the Inbox', () => {
  beforeEach(() => {
    incomingMock.mockReset();
    acceptMock.mockReset();
    declineMock.mockReset();
    toastSuccess.mockReset();
    toastError.mockReset();
  });

  it('names who invited and the role, and accepts at Origin', async () => {
    incomingMock.mockResolvedValueOnce([INV]).mockResolvedValueOnce([]);
    acceptMock.mockResolvedValue({ grant_id: 'claim-1' });
    render(<IncomingInvites />);
    await waitFor(() => expect(screen.getByText('Ann Lee')).toBeTruthy());
    expect(screen.getByText(/invited you as Viewer/)).toBeTruthy();
    fireEvent.click(screen.getByText('Accept'));
    await waitFor(() => expect(acceptMock).toHaveBeenCalledWith('inv-1'));
    await waitFor(() => expect(screen.queryByText('Ann Lee')).toBeNull());
    expect(toastSuccess).toHaveBeenCalled();
    expect(assign).toHaveBeenCalledWith('/W');
    expect(declineMock).not.toHaveBeenCalled();
  });

  it('declines at Origin', async () => {
    incomingMock.mockResolvedValueOnce([INV]).mockResolvedValueOnce([]);
    declineMock.mockResolvedValue({});
    render(<IncomingInvites />);
    await waitFor(() => expect(screen.getByText('Decline')).toBeTruthy());
    fireEvent.click(screen.getByText('Decline'));
    await waitFor(() => expect(declineMock).toHaveBeenCalledWith('inv-1'));
    expect(acceptMock).not.toHaveBeenCalled();
  });

  it('shows nothing when there are no invites, or Origin cannot be asked', async () => {
    incomingMock.mockRejectedValue(new Error('401'));
    const { container } = render(<IncomingInvites />);
    await waitFor(() => expect(incomingMock).toHaveBeenCalled());
    expect(container.textContent).toBe('');
  });

  it('a refused accept says so and keeps the invite listed', async () => {
    incomingMock.mockResolvedValue([INV]);
    acceptMock.mockRejectedValue(new Error('this invite does not name you'));
    render(<IncomingInvites />);
    await waitFor(() => expect(screen.getByText('Accept')).toBeTruthy());
    fireEvent.click(screen.getByText('Accept'));
    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(screen.getByText('Ann Lee')).toBeTruthy();
  });

  it('names roles as the share dialog does', () => {
    expect(roleOf(['read'])).toBe('Viewer');
    expect(roleOf(['create', 'read'])).toBe('Contributor');
    expect(roleOf(['create', 'read', 'update', 'delete'])).toBe('Editor');
    expect(roleOf(['read', 'share'])).toBe('Collaborator');
    expect(roleOf(['read', 'admin'])).toBe('Admin');
  });
});

// After Accept the grant reaches the store a few seconds later (2026-11-13, the Tester): Accept
// waits for it, then opens the item; past the wait it says access is on its way, never "not shared".
import { waitForAccess } from '../IncomingInvites';

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
