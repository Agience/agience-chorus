import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// Review 14, M4: the invite names the item open in the route, never an id Mantle's object gave;
// the owner confirms it by name, and Facet shows what Origin echoed back.
const listGrantsMock = vi.fn();
const createGrantMock = vi.fn();
vi.mock('@/api/collections', () => ({
  listGrants: (...a: unknown[]) => listGrantsMock(...a),
  deleteGrant: vi.fn(),
  createGrant: (...a: unknown[]) => createGrantMock(...a),
}));
const previewMock = vi.fn();
vi.mock('@/api/authority', async (orig) => ({
  describeParent: ((await orig()) as { describeParent: unknown }).describeParent,
  describeItem: ((await orig()) as { describeItem: unknown }).describeItem,
  describeGrantee: ((await orig()) as { describeGrantee: unknown }).describeGrantee,
  resendInviteAtOrigin: vi.fn(),
  previewAtOrigin: (...a: unknown[]) => previewMock(...a),
}));
vi.mock('@/hooks/useAuth', () => ({ useAuth: () => ({ user: { id: 'me-1' } }) }));
const toastError = vi.fn();
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: (...a: unknown[]) => toastError(...a) } }));

import { ShareDialog } from '../ShareDialog';

function renderAt(path: string, workspaceId: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/:artifactId" element={
          <ShareDialog open onOpenChange={() => {}} workspaceId={workspaceId} workspaceName="Plans" />} />
        <Route path="/" element={
          <ShareDialog open onOpenChange={() => {}} workspaceId={workspaceId} workspaceName="Plans" />} />
      </Routes>
    </MemoryRouter>,
  );
}

function ask(to: string) {
  fireEvent.change(screen.getByPlaceholderText('name@example.com'), { target: { value: to } });
  fireEvent.click(screen.getByText('Send invite'));
}

describe('ShareDialog — the invite names the item open in the route', () => {
  beforeEach(() => {
    listGrantsMock.mockReset();
    listGrantsMock.mockResolvedValue([]);
    createGrantMock.mockReset();
    toastError.mockReset();
    previewMock.mockReset();
    previewMock.mockResolvedValue({ resource_id: 'ws-1', parents: ['root-1'],
      parent_details: [{ id: 'root-1', creator: 'Alice Ng', created_at: '2026-10-02T09:00:00+00:00' }],
      resource_detail: { id: 'ws-1', creator: 'Bo Lee', created_at: '2026-10-20T09:00:00+00:00',
                         members: 7, grantees: 3 },
      grantees: [{ resource_id: 'ws-1', grantee_id: 'ann-1', grantee_type: 'user',
                   effect: 'allow', actions: ['read'], target_kind: null }], preview: 'DIGEST' });
  });

  it('refuses when the route and the workspace it was handed differ', async () => {
    renderAt('/ws-route', 'ws-other');
    ask('cy@example.invalid');
    await waitFor(() => expect(screen.getByTestId('invite-route-mismatch')).toBeTruthy());
    expect(createGrantMock).not.toHaveBeenCalled();
  });

  it('refuses when no item is open in the route', async () => {
    renderAt('/', 'ws-1');
    ask('cy@example.invalid');
    await waitFor(() => expect(screen.getByTestId('invite-route-mismatch')).toBeTruthy());
    expect(createGrantMock).not.toHaveBeenCalled();
  });

  it('asks the owner to confirm the item by name, sends that name, and shows Origin\'s echo', async () => {
    createGrantMock.mockResolvedValue({ id: 'g-new', grantee_type: 'invite',
      target_entity: 'cy@example.invalid',
      invite_echo: { resource_id: 'ws-1', resource_name: 'Plans', email: 'cy@example.invalid' } });
    renderAt('/ws-1', 'ws-1');
    ask('cy@example.invalid');
    expect(createGrantMock).not.toHaveBeenCalled();
    const confirm = await screen.findByTestId('invite-confirm');
    expect(confirm.textContent).toContain('Plans');
    expect(confirm.textContent).toContain('ws-1');
    expect(confirm.textContent).toContain('cy@example.invalid');
    // Origin's own preview of the item: its parent chain and who already holds it (review 15).
    const held = await screen.findByTestId('invite-preview');
    expect(previewMock).toHaveBeenCalledWith('ws-1');
    expect(held.textContent).toContain('root-1');
    // Review 16, L3: beside each parent id, who made it and when, as Origin holds them.
    expect(held.textContent).toContain('Alice Ng');
    expect(held.textContent).toContain('2026-10-02');
    // Review 17, L1: the item itself, as Origin holds it.
    expect(held.textContent).toContain('Bo Lee');
    expect(held.textContent).toContain('2026-10-20');
    expect(held.textContent).toContain('7 members');
    expect(held.textContent).toContain('3 grants');
    expect(held.textContent).toContain('ann-1');
    fireEvent.click(screen.getByText('Confirm and send'));
    await waitFor(() => expect(screen.getByTestId('invite-sent')).toBeTruthy());
    expect(createGrantMock).toHaveBeenCalledWith('ws-1', expect.objectContaining({
      resource_name: 'Plans', target_entity: 'cy@example.invalid', preview: 'DIGEST' }));
    const sent = screen.getByTestId('invite-sent').textContent || '';
    expect(sent).toContain('Origin');
    expect(sent).toContain('Plans');
    expect(sent).toContain('ws-1');
    expect(sent).toContain('cy@example.invalid');
  });
});
