// src/context/auth/__tests__/AuthProviderSso.test.jsx
//
// SSO return path: Origin (the IdP) sends an SP back with the token in the URL
// fragment. AuthProvider must consume it only when the fragment's state is one this
// browser issued, persist it, and scrub the fragment from the address bar. This is the
// mechanism that lets ONE Origin session serve my + lumen + mantle, and without the
// state check any `/#access_token=` link would replace the session (login CSRF).
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { AuthProvider } from '../AuthProvider';
import { useAuth } from '../../../hooks/useAuth';
import { issueSpState } from '../../../auth/spState';

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
    const state = issueSpState();
    setUrl({ hash: `#access_token=jwt-from-origin&state=${state}`, pathname: '/' });

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
    const state = issueSpState();
    setUrl({ hash: `#access_token=fresh-jwt&state=${state}`, pathname: '/' });

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

  describe('state check', () => {
    function renderProvider() {
      return render(
        <AuthProvider>
          <TestConsumer />
        </AuthProvider>,
      );
    }

    it.each([
      ['missing', '#access_token=attacker-jwt'],
      ['wrong', '#access_token=attacker-jwt&state=not-issued-here'],
      ['empty', '#access_token=attacker-jwt&state='],
    ])('ignores a fragment token whose state is %s and keeps the existing session', async (_label, hash) => {
      get.mockResolvedValue(mockUser);
      issueSpState(); // a sign-in is pending, but not with this state
      localStorage.setItem('access_token', 'victim-jwt');
      setUrl({ hash, pathname: '/' });

      renderProvider();

      await waitFor(() => expect(screen.getByTestId('authenticated')).toHaveTextContent('yes'));
      expect(localStorage.getItem('access_token')).toBe('victim-jwt');
      expect(get).toHaveBeenCalledTimes(1);
      // Scrubbed even though it was refused.
      expect(replaceStateSpy).toHaveBeenCalledWith(null, '', '/');
    });

    it('does not sign in from a fragment when no sign-in was started', async () => {
      setUrl({ hash: '#access_token=attacker-jwt&state=anything', pathname: '/' });

      renderProvider();

      await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('ready'));
      expect(screen.getByTestId('authenticated')).toHaveTextContent('no');
      expect(localStorage.getItem('access_token')).toBeNull();
      expect(get).not.toHaveBeenCalled();
    });

    it('accepts a matching state once and refuses a replay of it', async () => {
      get.mockResolvedValue(mockUser);
      const state = issueSpState();
      setUrl({ hash: `#access_token=first-jwt&state=${state}`, pathname: '/' });
      const first = renderProvider();
      await waitFor(() => expect(localStorage.getItem('access_token')).toBe('first-jwt'));
      first.unmount();

      localStorage.setItem('access_token', 'first-jwt');
      setUrl({ hash: `#access_token=replayed-jwt&state=${state}`, pathname: '/' });
      renderProvider();

      await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('ready'));
      expect(localStorage.getItem('access_token')).toBe('first-jwt');
    });

    it('accepts the hand-off in a different tab, which shares localStorage but not sessionStorage', async () => {
      get.mockResolvedValue(mockUser);
      const state = issueSpState();
      sessionStorage.clear();
      setUrl({ hash: `#access_token=verified-jwt&state=${state}`, pathname: '/' });

      renderProvider();

      await waitFor(() => expect(localStorage.getItem('access_token')).toBe('verified-jwt'));
    });

    it('refuses a state older than the one-hour window', async () => {
      const state = issueSpState(Date.now() - 61 * 60 * 1000);
      setUrl({ hash: `#access_token=late-jwt&state=${state}`, pathname: '/' });

      renderProvider();

      await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('ready'));
      expect(localStorage.getItem('access_token')).toBeNull();
    });
  });
});
