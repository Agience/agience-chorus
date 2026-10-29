import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// 2026-10-23, a tester: Share → invite said "Invite sent" and no mail came; the owner found no
// members, pending invites, revoke or resend.
const postMock = vi.fn();
vi.mock('@/api/api', () => ({ post: (...a: unknown[]) => postMock(...a) }));
const listGrantsMock = vi.fn();
const deleteGrantMock = vi.fn();
const resendInviteMock = vi.fn();
vi.mock('@/api/collections', () => ({
  listGrants: (...a: unknown[]) => listGrantsMock(...a),
  deleteGrant: (...a: unknown[]) => deleteGrantMock(...a),
  resendInvite: (...a: unknown[]) => resendInviteMock(...a),
}));
vi.mock('@/hooks/useAuth', () => ({ useAuth: () => ({ user: { id: 'me-1' } }) }));
const toastSuccess = vi.fn();
vi.mock('sonner', () => ({ toast: { success: (...a: unknown[]) => toastSuccess(...a), error: vi.fn() } }));

import { ShareDialog } from '../ShareDialog';

const ME = { id: 'g-me', grantee_type: 'user', grantee_id: 'me-1', state: 'active', can_read: true, can_admin: true,
  can_create: true, can_update: true, can_delete: true, can_evict: true, can_invoke: true, can_add: true, can_share: true };
const MEMBER = { id: 'g-ann', grantee_type: 'user', grantee_id: 'ann-12345678', name: 'ann@example.invalid',
  state: 'active', can_read: true };
const PENDING = { id: 'g-inv', grantee_type: 'invite', target_entity: 'bob@example.invalid',
  target_entity_type: 'email', state: 'active', can_read: true };

function renderDialog() {
  render(<ShareDialog open onOpenChange={() => {}} workspaceId="ws-1" workspaceName="Plans" />);
}

describe('ShareDialog — who has access, and whether an invite went', () => {
  beforeEach(() => {
    postMock.mockReset();
    listGrantsMock.mockReset();
    listGrantsMock.mockResolvedValue([ME, MEMBER, PENDING]);
    deleteGrantMock.mockReset();
    deleteGrantMock.mockResolvedValue(undefined);
    resendInviteMock.mockReset();
    toastSuccess.mockReset();
  });

  it('lists the members and pending invites, and removes a member', async () => {
    renderDialog();
    await waitFor(() => expect(screen.getByText('ann@example.invalid')).toBeTruthy());
    expect(screen.getByText('You')).toBeTruthy();
    expect(screen.getByText('bob@example.invalid')).toBeTruthy();
    expect(screen.getByText('Viewer · invite not yet accepted')).toBeTruthy();
    expect(screen.getAllByText('Remove').length).toBe(1);
    fireEvent.click(screen.getByText('Remove'));
    await waitFor(() => expect(deleteGrantMock).toHaveBeenCalledWith('g-ann'));
  });

  it('says an invite was sent only when its mail went, and otherwise gives the link', async () => {
    postMock.mockResolvedValue({ id: 'g-new', email_sent: false, claim_url: 'https://my.agience.ai/invite/tok' });
    renderDialog();
    fireEvent.change(screen.getByPlaceholderText('name@example.com'), { target: { value: 'cy@example.invalid' } });
    fireEvent.click(screen.getByText('Send invite'));
    await waitFor(() => expect(screen.getByTestId('invite-unsent')).toBeTruthy());
    expect((screen.getByLabelText('Invite link') as HTMLInputElement).value).toBe('https://my.agience.ai/invite/tok');
    expect(toastSuccess).not.toHaveBeenCalled();
  });

  it('resends a pending invite', async () => {
    resendInviteMock.mockResolvedValue({ id: 'g-inv', email_sent: true, claim_url: 'https://my.agience.ai/invite/new' });
    renderDialog();
    await waitFor(() => expect(screen.getByText('Resend')).toBeTruthy());
    fireEvent.click(screen.getByText('Resend'));
    await waitFor(() => expect(resendInviteMock).toHaveBeenCalledWith('g-inv'));
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith('Invite sent again to bob@example.invalid', expect.anything()));
  });

  it('offers no list to someone who may not manage access', async () => {
    listGrantsMock.mockRejectedValue({ response: { status: 403 } });
    renderDialog();
    await waitFor(() => expect(screen.queryByTestId('share-members')).toBeNull());
  });
});
