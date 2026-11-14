import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// Review 14's intent: what the owner confirms is what is shared. FR-030 (2026-11-14) shares any
// artifact by its own id: the dialog names it from the store by that id, binds the confirm to
// Origin's preview digest of exactly that id, and grants on it, whatever page is open.
const listGrantsMock = vi.fn();
const createGrantMock = vi.fn();
vi.mock('@/api/collections', () => ({
  listGrants: (...a: unknown[]) => listGrantsMock(...a),
  deleteGrant: vi.fn(),
  createGrant: (...a: unknown[]) => createGrantMock(...a),
}));
const previewMock = vi.fn();
vi.mock('@/api/authority', async (orig) => ({
  AuthorityRefused: ((await orig()) as { AuthorityRefused: unknown }).AuthorityRefused,
  describeParent: ((await orig()) as { describeParent: unknown }).describeParent,
  describeItem: ((await orig()) as { describeItem: unknown }).describeItem,
  describeGrantee: ((await orig()) as { describeGrantee: unknown }).describeGrantee,
  resendInviteAtOrigin: vi.fn(),
  previewAtOrigin: (...a: unknown[]) => previewMock(...a),
}));
const getArtifactMock = vi.fn();
vi.mock('@/api/artifacts', () => ({ getArtifact: (...a: unknown[]) => getArtifactMock(...a) }));
vi.mock('@/hooks/useAuth', () => ({ useAuth: () => ({ user: { id: 'me-1' } }) }));
const toastError = vi.fn();
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: (...a: unknown[]) => toastError(...a) } }));

import { ShareDialog } from '../ShareDialog';

function renderFor(resourceId: string, page = '/ws-route') {
  render(
    <MemoryRouter initialEntries={[page]}>
      <ShareDialog open onOpenChange={() => {}} resourceId={resourceId} />
    </MemoryRouter>,
  );
}

function ask(to: string) {
  fireEvent.change(screen.getByPlaceholderText('name@example.com'), { target: { value: to } });
  fireEvent.click(screen.getByText('Send invite'));
}

const PREVIEW = (id: string) => ({ resource_id: id, parents: ['root-1'],
  parent_details: [{ id: 'root-1', creator: 'Alice Ng', created_at: '2026-10-02T09:00:00+00:00' }],
  resource_detail: { id, creator: 'Bo Lee', created_at: '2026-10-20T09:00:00+00:00', members: 7, grantees: 3 },
  grantees: [{ resource_id: id, grantee_id: 'ann-1', grantee_type: 'user', effect: 'allow',
               actions: ['read'], target_kind: null }], preview: 'DIGEST-' + id });

describe('ShareDialog — any artifact, bound to its own id (FR-030)', () => {
  beforeEach(() => {
    listGrantsMock.mockReset();
    listGrantsMock.mockResolvedValue([]);
    createGrantMock.mockReset();
    toastError.mockReset();
    previewMock.mockReset();
    previewMock.mockImplementation(async (id: string) => PREVIEW(id));
    getArtifactMock.mockReset();
    getArtifactMock.mockImplementation(async (id: string) => ({ id, context: JSON.stringify({
      title: id === 'note-9' ? 'Meeting notes' : 'Plans',
      content_type: id === 'note-9' ? 'text/markdown' : 'application/vnd.agience.collection+json' }) }));
  });

  it('shares an artifact that is not the open page, by its own id and the name the store gives it', async () => {
    createGrantMock.mockResolvedValue({ id: 'g-new', grantee_type: 'invite', target_entity: 'cy@example.invalid',
      invite_echo: { resource_id: 'note-9', resource_name: 'Meeting notes', email: 'cy@example.invalid' } });
    renderFor('note-9', '/ws-route');
    await screen.findByText('Share Meeting notes');
    ask('cy@example.invalid');
    const confirm = await screen.findByTestId('invite-confirm');
    expect(confirm.textContent).toContain('Meeting notes');
    expect(confirm.textContent).toContain('note-9');
    await screen.findByTestId('invite-preview');
    expect(previewMock).toHaveBeenCalledWith('note-9');
    expect(screen.queryByTestId('invite-scope')).toBeNull(); // a note holds nothing
    fireEvent.click(screen.getByText('Confirm and send'));
    await waitFor(() => expect(screen.getByTestId('invite-sent')).toBeTruthy());
    expect(createGrantMock).toHaveBeenCalledWith('note-9', expect.objectContaining({
      resource_name: 'Meeting notes', target_entity: 'cy@example.invalid', preview: 'DIGEST-note-9' }));
  });

  it('says a container’s contents inherit what is shared, and shows where it inherits from', async () => {
    renderFor('ws-1');
    await screen.findByText('Share Plans');
    await waitFor(() => expect(screen.getByTestId('share-inherits').textContent).toContain('Plans'));
    ask('cy@example.invalid');
    await screen.findByTestId('invite-preview');
    expect(screen.getByTestId('invite-scope').textContent).toMatch(/everything inside it/);
  });

  it('refuses an id the store does not give this person, and sends nothing', async () => {
    getArtifactMock.mockRejectedValue(new Error('404'));
    renderFor('gone-1');
    await screen.findByText('Share this artifact');
    ask('cy@example.invalid');
    await waitFor(() => expect(screen.getByTestId('invite-route-mismatch')).toBeTruthy());
    expect(previewMock).not.toHaveBeenCalledWith('gone-1');
    expect(createGrantMock).not.toHaveBeenCalled();
  });

  it('never shows a name the caller passed: only the one the store gives for the id', async () => {
    render(
      <MemoryRouter initialEntries={['/x']}>
        <ShareDialog open onOpenChange={() => {}} resourceId="note-9" workspaceName="Payroll" />
      </MemoryRouter>,
    );
    await screen.findByText('Share Meeting notes');
    expect(screen.queryByText(/Payroll/)).toBeNull();
  });
});
