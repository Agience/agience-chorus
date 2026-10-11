// src/context/auth/__tests__/AuthProviderLogout.test.jsx
//
// Signing out of a service provider ends the IdP's session too. 2026-10-11: with my.agience.ai
// on Origin's SSO list, "Sign out" flashed the login page and came straight back signed in,
// because Origin still held a session and handed a new token to the next visit.
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

const runtime = vi.hoisted(() => ({ idpUri: '' }));
vi.mock('../../../config/runtime', () => ({
  getRuntimeConfig: () => ({ originUri: 'https://my.agience.ai', clientId: 'platform', ...runtime }),
}));
vi.mock('../../../api/api', () => ({ get: vi.fn(), del: vi.fn() }));

import { get } from '../../../api/api';
import { AuthProvider } from '../AuthProvider';
import { useAuth } from '../../../hooks/useAuth';

function SignOut() {
  const auth = useAuth();
  return (
    <div>
      <div data-testid="authenticated">{auth.isAuthenticated ? 'yes' : 'no'}</div>
      <button onClick={auth.logout}>sign out</button>
    </div>
  );
}

describe('AuthProvider — sign out', () => {
  let assign;

  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    vi.clearAllMocks();
    get.mockResolvedValue({ id: 'u1', email: 'a@example.com', name: 'A' });
    localStorage.setItem('access_token', 'jwt');
    assign = vi.fn();
    delete window.location;
    window.location = { hash: '', pathname: '/', search: '', origin: 'https://my.agience.ai', assign };
  });

  async function signOut() {
    render(<AuthProvider><SignOut /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId('authenticated')).toHaveTextContent('yes'));
    fireEvent.click(screen.getByText('sign out'));
  }

  it('as a service provider, clears its token and ends the IdP session', async () => {
    runtime.idpUri = 'https://origin.agience.ai/';
    await signOut();
    expect(localStorage.getItem('access_token')).toBeNull();
    expect(assign).toHaveBeenCalledWith(
      'https://origin.agience.ai/logout?return=https%3A%2F%2Fmy.agience.ai%2F');
  });

  it('as the IdP itself, signs out locally and goes nowhere', async () => {
    runtime.idpUri = '';
    await signOut();
    expect(localStorage.getItem('access_token')).toBeNull();
    expect(assign).not.toHaveBeenCalled();
  });
});
