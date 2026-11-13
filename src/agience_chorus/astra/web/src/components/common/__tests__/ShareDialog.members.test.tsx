import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// 2026-10-23, a tester: Share → invite said "Invite sent" and no mail came; the owner found no
// members, pending invites, revoke or resend.
const postMock = vi.fn();
vi.mock('@/api/api', () => ({ post: (...a: unknown[]) => postMock(...a) }));
const listGrantsMock = vi.fn();
const deleteGrantMock = vi.fn();
const createGrantMock = vi.fn();
vi.mock('@/api/collections', () => ({
  listGrants: (...a: unknown[]) => listGrantsMock(...a),
  deleteGrant: (...a: unknown[]) => deleteGrantMock(...a),
  createGrant: (...a: unknown[]) => createGrantMock(...a),
}));
// Round 13: an invite is made at Origin for one address, and Origin mails it; Facet never holds
// the link.
const resendAtOriginMock = vi.fn();
vi.mock('@/api/authority', async (orig) => ({
  AuthorityRefused: ((await orig()) as { AuthorityRefused: unknown }).AuthorityRefused,
  describeParent: ((await orig()) as { describeParent: unknown }).describeParent,
  describeItem: ((await orig()) as { describeItem: unknown }).describeItem,
  describeGrantee: ((await orig()) as { describeGrantee: unknown }).describeGrantee,
  resendInviteAtOrigin: (...a: unknown[]) => resendAtOriginMock(...a),
  // Origin's preview, which every make names and the owner confirms (review 15).
  previewAtOrigin: async (id: string) => ({ resource_id: id, parents: [], grantees: [],
                                            preview: 'D' }),
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
  // The item open in the route is the one shared (review 14).
  render(
    <MemoryRouter initialEntries={['/ws-1']}>
      <Routes>
        <Route path="/:artifactId" element={
          <ShareDialog open onOpenChange={() => {}} workspaceId="ws-1" workspaceName="Plans" />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('ShareDialog — who has access, and whether an invite went', () => {
  beforeEach(() => {
    postMock.mockReset();
    listGrantsMock.mockReset();
    listGrantsMock.mockResolvedValue([ME, MEMBER, PENDING]);
    deleteGrantMock.mockReset();
    deleteGrantMock.mockResolvedValue(undefined);
    createGrantMock.mockReset();
    resendAtOriginMock.mockReset();
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
    await waitFor(() => expect(deleteGrantMock).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'g-ann' })));
  });

  it('makes the invite at Origin for one address, which Origin mails, and shows no link', async () => {
    createGrantMock.mockResolvedValue({ id: 'g-new', grantee_type: 'invite',
                                        target_entity: 'cy@example.invalid' });
    renderDialog();
    fireEvent.change(screen.getByPlaceholderText('name@example.com'), { target: { value: 'cy@example.invalid' } });
    fireEvent.click(screen.getByText('Send invite'));
    fireEvent.click(await screen.findByText('Confirm and send'));
    await waitFor(() => expect(screen.getByTestId('invite-sent')).toBeTruthy());
    expect(createGrantMock).toHaveBeenCalledWith('ws-1', expect.objectContaining({
      grantee_type: 'invite', target_entity: 'cy@example.invalid', target_entity_type: 'email' }));
    expect(screen.getByTestId('invite-sent').textContent).toContain('cy@example.invalid');
    expect(screen.queryByLabelText('Invite link')).toBeNull();
    expect(postMock).not.toHaveBeenCalled();
  });

  it('a pending invite is sent again by Origin to its address, and shows no link', async () => {
    resendAtOriginMock.mockResolvedValue({ id: 'g-inv2', grantee_type: 'invite' });
    // The owner confirms Origin's preview of the item again (review 15).
    const asked = vi.spyOn(window, 'confirm').mockReturnValue(true);
    renderDialog();
    await waitFor(() => expect(screen.getByText('Resend')).toBeTruthy());
    fireEvent.click(screen.getByText('Resend'));
    await waitFor(() => expect(resendAtOriginMock).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'g-inv' }), 'bob@example.invalid', 'D'));
    expect(asked).toHaveBeenCalled();
    asked.mockRestore();
    await waitFor(() => expect(screen.getByTestId('invite-sent').textContent)
      .toContain('bob@example.invalid'));
    expect(screen.queryByLabelText('Invite link')).toBeNull();
  });

  it('offers no list to someone who may not manage access', async () => {
    listGrantsMock.mockRejectedValue({ response: { status: 403 } });
    renderDialog();
    await waitFor(() => expect(screen.queryByTestId('share-members')).toBeNull());
  });
});

// 2026-11-08, the local check: after Bob accepted, the owner's dialog still listed the spent invite
// as "invite not yet accepted", with Resend and Revoke, and Bob as "Someone (dad18e7c)".
describe('ShareDialog — an accepted invite, and members by name', () => {
  beforeEach(() => {
    listGrantsMock.mockReset();
  });

  it('drops an invite whose claims are spent, and names the member Origin names', async () => {
    listGrantsMock.mockResolvedValue([
      ME,
      { id: 'g-bob', grantee_type: 'user', grantee_id: 'dad18e7c-0000', name: 'Bob', state: 'active',
        can_read: true },
      { ...PENDING, id: 'g-spent', target_entity: undefined, max_claims: 1, claims_count: 1 },
    ]);
    renderDialog();
    await waitFor(() => expect(screen.getByText('Bob')).toBeTruthy());
    expect(screen.queryByText(/invite not yet accepted/)).toBeNull();
    expect(screen.queryByText('Resend')).toBeNull();
    expect(screen.queryByText(/Someone \(/)).toBeNull();
  });
});
