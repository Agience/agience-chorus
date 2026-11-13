import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// FR-004: an invite's target can decline it in the app. Origin retires it with no claim, and its
// sender's share dialog says so instead of the invite vanishing.
vi.mock('@/api/api', () => ({ post: vi.fn() }));
const listGrantsMock = vi.fn();
vi.mock('@/api/collections', () => ({
  listGrants: (...a: unknown[]) => listGrantsMock(...a),
  deleteGrant: vi.fn(),
  createGrant: vi.fn(),
}));
vi.mock('@/api/authority', async (orig) => ({
  AuthorityRefused: ((await orig()) as { AuthorityRefused: unknown }).AuthorityRefused,
  describeParent: ((await orig()) as { describeParent: unknown }).describeParent,
  describeItem: ((await orig()) as { describeItem: unknown }).describeItem,
  describeGrantee: ((await orig()) as { describeGrantee: unknown }).describeGrantee,
  resendInviteAtOrigin: vi.fn(),
  previewAtOrigin: async (id: string) => ({ resource_id: id, parents: [], grantees: [],
                                            preview: 'D' }),
}));
vi.mock('@/hooks/useAuth', () => ({ useAuth: () => ({ user: { id: 'me-1' } }) }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { ShareDialog } from '../ShareDialog';

const ME = { id: 'g-me', grantee_type: 'user', grantee_id: 'me-1', state: 'active', can_read: true,
  can_admin: true, can_create: true, can_update: true, can_delete: true, can_evict: true,
  can_invoke: true, can_add: true, can_share: true };
const DECLINED = { id: 'g-dec', grantee_type: 'invite', target_entity: 'bob@example.invalid',
  target_entity_type: 'email', state: 'retired', can_read: true, claims_count: 0, max_claims: 1 };
const REVOKED = { id: 'g-rev', grantee_type: 'invite', target_entity: 'cy@example.invalid',
  target_entity_type: 'email', state: 'revoked', can_read: true, claims_count: 0, max_claims: 1 };

function renderDialog() {
  render(
    <MemoryRouter initialEntries={['/ws-1']}>
      <Routes>
        <Route path="/:artifactId" element={
          <ShareDialog open onOpenChange={() => {}} workspaceId="ws-1" workspaceName="Plans" />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('ShareDialog — an invite declined in the app', () => {
  beforeEach(() => {
    listGrantsMock.mockReset();
    listGrantsMock.mockResolvedValue([ME, DECLINED, REVOKED]);
  });

  it('shows a declined invite as declined, with no Resend, and leaves a revoked one out', async () => {
    renderDialog();
    await waitFor(() => expect(screen.getByText('bob@example.invalid')).toBeTruthy());
    expect(screen.getByText('Viewer · invite declined')).toBeTruthy();
    expect(screen.queryByText('Resend')).toBeNull();
    expect(screen.queryByText('cy@example.invalid')).toBeNull();
  });
});
