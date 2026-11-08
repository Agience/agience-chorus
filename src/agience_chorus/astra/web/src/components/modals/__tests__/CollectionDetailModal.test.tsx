import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import CollectionDetailModal from '../CollectionDetailModal';

const listCollectionsMock = vi.fn();
const listGrantsMock = vi.fn();
const createGrantMock = vi.fn();

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    user: { id: 'user-1' },
  }),
}));

vi.mock('@/hooks/useWorkspaces', () => ({
  useWorkspaces: () => ({ activeWorkspaceId: 'ws-1' }),
}));

vi.mock('@/api/collections', () => ({
  listCollections: (...args: unknown[]) => listCollectionsMock(...args),
  listGrants: (...args: unknown[]) => listGrantsMock(...args),
  createCollection: vi.fn(),
  updateCollection: vi.fn(),
  deleteCollection: vi.fn(),
  createGrant: (...args: unknown[]) => createGrantMock(...args),
  updateGrant: vi.fn(),
  deleteGrant: vi.fn(),
}));

// Origin's preview, which every make names and the owner confirms (review 15).
vi.mock('@/api/authority', async (orig) => ({
  describeParent: ((await orig()) as { describeParent: unknown }).describeParent,
  describeItem: ((await orig()) as { describeItem: unknown }).describeItem,
  describeGrantee: ((await orig()) as { describeGrantee: unknown }).describeGrantee,
  previewAtOrigin: async (id: string) => ({ resource_id: id, parents: ['root-9'],
    grantees: [{ resource_id: id, grantee_id: 'ann-1', grantee_type: 'user', effect: 'allow',
                 actions: ['read'] }], preview: 'D' }),
}));

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

describe('CollectionDetailModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    listCollectionsMock.mockResolvedValue([
      {
        id: 'col-1',
        name: 'Main Collection',
        description: 'Primary collection',
        created_by: 'user-1',
        created_time: '2026-03-21T00:00:00Z',
        modified_time: '2026-03-21T00:00:00Z',
      },
    ]);
    listGrantsMock.mockResolvedValue([]);
  });

  // 2026-10-22 (John): commits are not part of the model; each change is a new version of its root.
  it("shows the collection's sharing and no commit history", async () => {
    render(<CollectionDetailModal open onClose={vi.fn()} />);
    await waitFor(() => expect(listGrantsMock).toHaveBeenCalledWith('col-1'));
    expect(screen.queryByText('Commit History')).toBeNull();
  });

  // Round 13: an invite is made at Origin for one address, which Origin mails; no key or link is
  // ever shown, and none is made without an address.
  it('makes an invite for one address and shows no key or link', async () => {
    listGrantsMock.mockResolvedValue([{ id: 'inv-1', grantee_type: 'invite', target_entity: 'bob@x.test',
                                        can_read: true, claim_token: 'SECRET-LINK-TOKEN' }]);
    createGrantMock.mockResolvedValue({ id: 'inv-2', grantee_type: 'invite',
                                        target_entity: 'carol@x.test', can_read: true });
    render(<CollectionDetailModal open onClose={vi.fn()} />);
    await waitFor(() => expect(listGrantsMock).toHaveBeenCalledWith('col-1'));
    expect(await screen.findByText('bob@x.test')).toBeTruthy();
    expect(screen.queryByText('SECRET-LINK-TOKEN')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /invite/i }));
    const address = await screen.findByPlaceholderText(/email/i);
    fireEvent.change(address, { target: { value: 'carol@x.test' } });
    fireEvent.click(screen.getByRole('button', { name: /^send invite$/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^confirm and send$/i }));
    await waitFor(() => expect(createGrantMock).toHaveBeenCalled());
    expect(createGrantMock.mock.calls[0][1]).toMatchObject({
      grantee_type: 'invite', target_entity: 'carol@x.test', target_entity_type: 'email' });
  });

  // Review 14: the owner confirms the item by the name and id they see, that name goes to Origin,
  // and what Origin echoed is shown. No grant here is "identified" or not: the checkboxes are gone.
  it("confirms the item by name, sends that name and shows Origin's echo", async () => {
    createGrantMock.mockResolvedValue({ id: 'inv-2', grantee_type: 'invite',
      target_entity: 'carol@x.test', can_read: true,
      invite_echo: { resource_id: 'col-1', resource_name: 'Main Collection', email: 'carol@x.test' } });
    render(<CollectionDetailModal open onClose={vi.fn()} />);
    await waitFor(() => expect(listGrantsMock).toHaveBeenCalledWith('col-1'));
    fireEvent.click(screen.getByRole('button', { name: /invite/i }));
    expect(screen.queryByText(/Require Identity/)).toBeNull();
    fireEvent.change(await screen.findByPlaceholderText(/email/i), { target: { value: 'carol@x.test' } });
    fireEvent.click(screen.getByRole('button', { name: /^send invite$/i }));
    const confirm = await screen.findByTestId('grant-invite-confirm');
    const held = await screen.findByTestId('grant-invite-preview');
    expect(held.textContent).toContain('root-9');
    expect(held.textContent).toContain('ann-1');
    expect(confirm.textContent).toContain('Main Collection');
    expect(confirm.textContent).toContain('col-1');
    expect(createGrantMock).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: /^confirm and send$/i }));
    await waitFor(() => expect(createGrantMock).toHaveBeenCalledWith('col-1', expect.objectContaining({
      resource_name: 'Main Collection', target_entity: 'carol@x.test', preview: 'D' })));
    const echo = await screen.findByTestId('grant-invite-echo');
    expect(echo.textContent).toContain('Main Collection');
    expect(echo.textContent).toContain('col-1');
    expect(echo.textContent).toContain('carol@x.test');
  });
});
