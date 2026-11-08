import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// 2026-10-31, a tester: a Viewer opened "Share REG-WS" and got an enabled Send invite form, which
// Origin then refused for lack of Share or Admin. Origin shows a resource's grants only to someone
// who may share it, so a refused listing means the invite controls are off, with the reason shown.
// A plain function, not a vi.fn: the spy's own tracking of a rejected promise surfaces as the test's
// error even though the dialog handles it.
let listGrantsImpl: () => Promise<unknown[]> = async () => [];
let listGrantsCalls = 0;
vi.mock('@/api/collections', () => ({
  listGrants: () => { listGrantsCalls += 1; return listGrantsImpl(); },
  deleteGrant: vi.fn(),
  createGrant: vi.fn(),
}));
vi.mock('@/api/authority', async (orig) => ({
  describeParent: ((await orig()) as { describeParent: unknown }).describeParent,
  describeItem: ((await orig()) as { describeItem: unknown }).describeItem,
  describeGrantee: ((await orig()) as { describeGrantee: unknown }).describeGrantee,
  resendInviteAtOrigin: vi.fn(),
  previewAtOrigin: vi.fn(),
}));
vi.mock('@/hooks/useAuth', () => ({ useAuth: () => ({ user: { id: 'me-1' } }) }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { ShareDialog } from '../ShareDialog';

function renderShare() {
  render(
    <MemoryRouter initialEntries={['/ws-1']}>
      <Routes>
        <Route path="/:artifactId" element={
          <ShareDialog open onOpenChange={() => {}} workspaceId="ws-1" workspaceName="REG-WS" />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('ShareDialog for someone who may not share', () => {
  beforeEach(() => { listGrantsCalls = 0; });

  it('turns the invite controls off and says why', async () => {
    listGrantsImpl = async () => { throw Object.assign(new Error('forbidden'), { response: { status: 403 } }); };
    renderShare();
    await waitFor(() => expect(screen.getByTestId('invite-not-permitted')).toBeTruthy());
    expect((screen.getByPlaceholderText('name@example.com') as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByText('Send invite') as HTMLButtonElement).disabled).toBe(true);
  });

  it('leaves them on for a sharer', async () => {
    listGrantsImpl = async () => [];
    renderShare();
    await waitFor(() => expect(listGrantsCalls).toBeGreaterThan(0));
    expect(screen.queryByTestId('invite-not-permitted')).toBeNull();
    expect((screen.getByPlaceholderText('name@example.com') as HTMLInputElement).disabled).toBe(false);
  });
});
