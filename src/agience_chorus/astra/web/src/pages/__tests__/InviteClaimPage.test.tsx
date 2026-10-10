import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import InviteClaimPage from '../InviteClaimPage';

const { getMock, claimInviteMock } = vi.hoisted(() => ({
  getMock: vi.fn(),
  claimInviteMock: vi.fn(),
}));

vi.mock('../../api/api', () => ({
  get: (...args: unknown[]) => getMock(...args),
}));

vi.mock('../../api/artifacts', () => ({
  claimInvite: (...args: unknown[]) => claimInviteMock(...args),
}));

vi.mock('../../hooks/useAuth', () => ({
  useAuth: () => ({ isAuthenticated: true, loading: false, login: vi.fn() }),
}));

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function answer(url: string) {
  if (url.startsWith('/grants/invite-context')) return Promise.resolve({ valid: true, has_target: false });
  if (url.startsWith('/grants/invite-details')) {
    return Promise.resolve({ valid: true, name: 'Q3 research', resource_id: 'col-42', granted_by: 'user-7' });
  }
  return Promise.reject(new Error(`unexpected GET ${url}`));
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/invite/tok-1']}>
      <Routes>
        <Route path="/invite/:token" element={<InviteClaimPage />} />
        <Route path="/" element={<div>home</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('InviteClaimPage', () => {
  beforeEach(() => {
    getMock.mockReset();
    getMock.mockImplementation(answer);
    claimInviteMock.mockReset();
    claimInviteMock.mockResolvedValue({ resource_id: 'col-42' });
    sessionStorage.clear();
  });

  it('shows what is being claimed and sends no claim before the click', async () => {
    renderPage();

    expect(await screen.findByText('Accept this invite?')).toBeInTheDocument();
    expect(screen.getByText('Q3 research')).toBeInTheDocument();
    expect(screen.getByText('col-42')).toBeInTheDocument();
    expect(screen.getByText('user-7')).toBeInTheDocument();
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
    getMock.mockImplementation((url: string) =>
      url.startsWith('/grants/invite-details')
        ? Promise.resolve({ valid: true, identity_mismatch: true })
        : answer(url),
    );
    renderPage();

    expect(await screen.findByText(/addressed to a different account/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Accept invite' })).toBeNull();
    expect(claimInviteMock).not.toHaveBeenCalled();
  });
});
