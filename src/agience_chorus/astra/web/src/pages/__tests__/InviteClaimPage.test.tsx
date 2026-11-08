import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import InviteClaimPage from '../InviteClaimPage';

const { getMock, postMock, contextMock, claimInviteMock } = vi.hoisted(() => ({
  getMock: vi.fn(),
  postMock: vi.fn(),
  contextMock: vi.fn(),
  claimInviteMock: vi.fn(),
}));

// Mantle's client: the page must never call it with the invite's token (round 13).
vi.mock('../../api/api', () => ({
  get: (...args: unknown[]) => getMock(...args),
  post: (...args: unknown[]) => postMock(...args),
}));

vi.mock('../../api/authority', () => ({
  inviteContext: (...args: unknown[]) => contextMock(...args),
}));

vi.mock('../../api/artifacts', () => ({
  claimInvite: (...args: unknown[]) => claimInviteMock(...args),
}));

vi.mock('../../hooks/useAuth', () => ({
  useAuth: () => ({ isAuthenticated: true, loading: false, login: vi.fn(),
                    user: { id: 'me-1', email: 'una@example.invalid' } }),
}));

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/invite/tok-1']}>
      <Routes>
        <Route path="/invite/:token" element={<InviteClaimPage />} />
        <Route path="/" element={<div>home</div>} />
        <Route path="/:id" element={<div>opened</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('InviteClaimPage', () => {
  beforeEach(() => {
    getMock.mockReset();
    contextMock.mockReset();
    contextMock.mockResolvedValue({ invite_id: 'inv-1', resource_id: 'col-42', actions: ['read'],
                                    state: 'active', for_you: true });
    claimInviteMock.mockReset();
    claimInviteMock.mockResolvedValue({ resource_id: 'col-42' });
    getMock.mockResolvedValue({ id: 'col-42' });
    postMock.mockReset();
    postMock.mockResolvedValue({ sent: true });
    sessionStorage.clear();
  });

  it('shows what is being claimed, read from Origin, and sends no claim before the click', async () => {
    renderPage();

    expect(await screen.findByText('Accept this invite?')).toBeInTheDocument();
    expect(screen.getByText('col-42')).toBeInTheDocument();
    expect(screen.getByText('read')).toBeInTheDocument();
    expect(contextMock).toHaveBeenCalledWith('tok-1');
    expect(getMock).not.toHaveBeenCalled();                 // the token never reaches Mantle
    expect(claimInviteMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Accept invite' }));

    await waitFor(() => expect(claimInviteMock).toHaveBeenCalledWith('tok-1'));
    expect(claimInviteMock).toHaveBeenCalledTimes(1);
  });

  it('Cancel leaves without claiming and forgets the pending invite', async () => {
    sessionStorage.setItem('pending_invite_token', 'tok-1');
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: 'Cancel' }));

    expect(await screen.findByText('home')).toBeInTheDocument();
    expect(claimInviteMock).not.toHaveBeenCalled();
    expect(sessionStorage.getItem('pending_invite_token')).toBeNull();
  });

  it('offers no Accept when the invite is addressed to another account', async () => {
    contextMock.mockResolvedValue({ invite_id: 'inv-1', resource_id: 'col-42', actions: ['read'],
                                    state: 'active', for_you: false });
    renderPage();

    expect(await screen.findByText(/addressed to a different account/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Accept invite' })).toBeNull();
    expect(claimInviteMock).not.toHaveBeenCalled();
    expect(getMock).not.toHaveBeenCalled();
  });

  // 2026-11-08, the local check: with email verification off, the real recipient's address was
  // unverified, and the page said the invite was addressed to a different account.
  it('asks for a verified address first, with a way to verify, when the address is not', async () => {
    contextMock.mockResolvedValue({ invite_id: 'inv-1', resource_id: 'col-42', actions: ['read'],
                                    state: 'active', for_you: false, address_verified: false });
    renderPage();

    expect(await screen.findByText(/verify your email address/i)).toBeInTheDocument();
    expect(screen.queryByText(/different account/)).toBeNull();
    expect(screen.queryByRole('button', { name: 'Accept invite' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /send me a verification link/i }));
    await waitFor(() => expect(postMock).toHaveBeenCalledWith('/auth/email/verify-request',
                                                              { email: 'una@example.invalid' }));
  });

  // 2026-11-08, the local check: after accepting, the workspace was refused for about 15 s,
  // until Mantle applied Origin's feed. The page waits for access, saying so, then opens it.
  it('says it is setting up access until Mantle opens the item, then opens it', async () => {
    getMock.mockReset();
    getMock.mockRejectedValueOnce(Object.assign(new Error('403'), { response: { status: 403 } }))
      .mockResolvedValue({ id: 'col-42' });
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: 'Accept invite' }));
    expect(await screen.findByText(/setting up access/i)).toBeInTheDocument();
    expect(await screen.findByText('opened', {}, { timeout: 5000 })).toBeInTheDocument();
    expect(getMock).toHaveBeenCalledWith('/artifacts/col-42');
    expect(getMock.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  // Review of the local-check fixes: the wait stops when the page goes, and when Origin holds no
  // session for this browser (asking again would only be refused again).
  it('stops waiting when the page is left', async () => {
    getMock.mockReset();
    getMock.mockRejectedValue(Object.assign(new Error('403'), { response: { status: 403 } }));
    const view = renderPage();
    fireEvent.click(await screen.findByRole('button', { name: 'Accept invite' }));
    await waitFor(() => expect(getMock).toHaveBeenCalledTimes(1));
    view.unmount();
    const seen = getMock.mock.calls.length;
    await new Promise((r) => setTimeout(r, 2500));
    expect(getMock.mock.calls.length).toBe(seen);
  });

  it('stops waiting when Origin holds no session, and says to sign in again', async () => {
    const { SessionTokenRefused } = await import('../../auth/sessionToken');
    getMock.mockReset();
    getMock.mockRejectedValue(new SessionTokenRefused(401, 'mantle-token'));
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: 'Accept invite' }));
    expect(await screen.findByText(/sign in again/i)).toBeInTheDocument();
    const seen = getMock.mock.calls.length;
    await new Promise((r) => setTimeout(r, 2500));
    expect(getMock.mock.calls.length).toBe(seen);
    expect(seen).toBe(1);
  });
});
