// src/context/auth/__tests__/AuthProviderSso.test.jsx
//
// SSO return path: Origin (the IdP) sends an SP back with the token in the URL
// fragment. AuthProvider must consume it, persist it, and scrub it from the address
// bar. This is the mechanism that lets ONE Origin session serve my + lumen + mantle,
// so it's worth pinning down.
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { AuthProvider } from '../AuthProvider';
import { useAuth } from '../../../hooks/useAuth';

vi.mock('../../../api/api', () => ({
  get: vi.fn(),
  del: vi.fn(),
}));

import { get } from '../../../api/api';

function TestConsumer() {
  const auth = useAuth();
  return (
    <div>
      <div data-testid="loading">{auth.loading ? 'loading' : 'ready'}</div>
      <div data-testid="authenticated">{auth.isAuthenticated ? 'yes' : 'no'}</div>
    </div>
  );
}

describe('AuthProvider — SSO fragment return path', () => {
  const mockUser = { id: 'u1', email: 'op@agience.ai', name: 'Operator' };
  let replaceStateSpy;

  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    vi.clearAllMocks();
    replaceStateSpy = vi.spyOn(window.history, 'replaceState').mockImplementation(() => {});
    window.history.replaceState = replaceStateSpy;
  });

  function setUrl({ hash = '', pathname = '/', search = '' }) {
    // jsdom's location is read-only; redefine just what AuthProvider reads.
    delete window.location;
    window.location = { hash, pathname, search, origin: 'https://my.agience.ai' };
  }

  it('consumes an access_token from the fragment, persists it, and scrubs the URL', async () => {
    get.mockResolvedValue(mockUser);
    setUrl({ hash: '#access_token=jwt-from-origin&state=st-abc', pathname: '/' });

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );

    await waitFor(() => expect(screen.getByTestId('authenticated')).toHaveTextContent('yes'));
    // Persisted, so a reload keeps the session without another IdP round-trip.
    expect(localStorage.getItem('access_token')).toBe('jwt-from-origin');
    // Scrubbed, so the JWT isn't left sitting in browser history.
    expect(replaceStateSpy).toHaveBeenCalledWith(null, '', '/');
  });

  it('prefers the fragment token over a stale one already in localStorage', async () => {
    get.mockResolvedValue(mockUser);
    localStorage.setItem('access_token', 'stale-jwt');
    setUrl({ hash: '#access_token=fresh-jwt', pathname: '/' });

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );

    await waitFor(() => expect(localStorage.getItem('access_token')).toBe('fresh-jwt'));
  });

  it('falls back to localStorage when there is no fragment', async () => {
    get.mockResolvedValue(mockUser);
    localStorage.setItem('access_token', 'existing-jwt');
    setUrl({ hash: '', pathname: '/' });

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );

    await waitFor(() => expect(screen.getByTestId('authenticated')).toHaveTextContent('yes'));
    expect(replaceStateSpy).not.toHaveBeenCalled();
  });

  it('ignores an unrelated fragment and does not authenticate', async () => {
    setUrl({ hash: '#section=overview', pathname: '/' });

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );

    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('ready'));
    expect(screen.getByTestId('authenticated')).toHaveTextContent('no');
    expect(localStorage.getItem('access_token')).toBeNull();
  });
});
