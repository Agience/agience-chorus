import React, { useState, ReactNode, useEffect, useCallback } from 'react';
import { get, del } from '../../api/api';
import { getRuntimeConfig } from '../../config/runtime';
import { User } from './auth.types';
import { AuthContext } from './AuthContext';
import { consumeSpState } from '../../auth/spState';
import { forgetMantleToken } from '../../auth/mantleToken';
import { originFreshSignInUrl } from '../../auth/originSignIn';

const { originUri, clientId: CLIENT_ID } = getRuntimeConfig();
// Without a trailing slash: in local development `originUri` is `/` (Origin through the dev server),
// and `//auth/authorize` would name a host called "auth".
const ORIGIN_URI = originUri.replace(/\/+$/, '');

export const AuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [loading, setLoading] = useState(true);
  // Set while the page leaves to sign out (the IdP's `/logout`) or to sign in again (Origin's
  // form): the workspace is replaced at once, so it is not left on screen (and usable) while that
  // navigation completes.
  const [leaving, setLeaving] = useState<string | null>(null);

  useEffect(() => {
    // SP return path: Origin (the IdP) sends us back with the token in the URL
    // fragment. The token is accepted only when the fragment's `state` is one this
    // browser issued when it started the sign-in (`auth/spState`), and each state is
    // accepted once. Any other fragment token is discarded and the existing session is
    // left as it is. The fragment is scrubbed from the address bar either way, so the
    // JWT isn't left in history. The fragment never reaches a server.
    const hash = window.location.hash;
    if (hash && hash.indexOf('access_token=') !== -1) {
      const frag = new URLSearchParams(hash.replace(/^#/, ''));
      const t = frag.get('access_token');
      const fragToken = t && t.trim() ? t : null;
      window.history.replaceState(null, '', window.location.pathname + window.location.search);
      if (fragToken && consumeSpState(frag.get('state'))) {
        console.log('[AuthProvider] mount — token arrived in fragment from the IdP');
        localStorage.setItem('access_token', fragToken);
        setToken(fragToken);
        return;
      }
      console.warn('[AuthProvider] mount — fragment token discarded: state missing or not issued here');
    }

    const localToken = localStorage.getItem('access_token');
    console.log('[AuthProvider] mount — token in localStorage:', !!localToken);
    if (!localToken) {
      setLoading(false);
      return;
    }
    setToken(localToken);
  }, []);

  useEffect(() => {
    if (!token) return;

    const controller = new AbortController();
    setLoading(true);
    console.log('[AuthProvider] token effect — fetching /auth/userinfo');
    get<User>('/auth/userinfo', { signal: controller.signal })
      .then((res) => {
        console.log('[AuthProvider] /auth/userinfo OK — user:', res?.email ?? res?.name ?? 'unknown');
        setUser(res);
        setIsAuthenticated(true);
      })
      .catch((err) => {
        if (controller.signal.aborted || err?.code === 'ERR_CANCELED') {
          console.log('[AuthProvider] /auth/userinfo aborted (cleanup)');
          return;
        }
        console.warn('[AuthProvider] /auth/userinfo FAILED:', err);
        localStorage.removeItem('access_token');
        setToken(null);
        setUser(null);
        setIsAuthenticated(false);
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          console.log('[AuthProvider] loading → false');
          setLoading(false);
        }
      });

    return () => controller.abort();
  }, [token]);

  const setAuthData = (token: string | null) => {
    if (!token) {
      localStorage.removeItem('access_token');
      setToken(null);
      setUser(null);
      setIsAuthenticated(false);
      return;
    }

    console.log('[AuthProvider] setAuthData — storing token, triggering validation');
    localStorage.setItem('access_token', token);
    setLoading(true);  // must be synchronous so LoginProtected shows spinner
    setToken(token);    // triggers validation effect
    setUser(null);      // clear stale user
  };

  // With no provider named, Origin shows its own chooser: every method this node has.
  const login = async (provider: string = 'local', setupOperatorToken?: string) => {
    const state = crypto.randomUUID();
    const codeVerifier = Array.from(crypto.getRandomValues(new Uint8Array(32)))
      .map(b => b.toString(16).padStart(2, '0'))
      .join('');

    const encoder = new TextEncoder();
    const data = encoder.encode(codeVerifier);
    const digest = await crypto.subtle.digest('SHA-256', data);
    const base64Url = btoa(String.fromCharCode(...new Uint8Array(digest)))
      .replace(/\+/g, '-')
      .replace(/\//g, '_')
      .replace(/=+$/, '');

    localStorage.setItem('pkce_state', state);
    localStorage.setItem('pkce_verifier', codeVerifier);

    const params = new URLSearchParams({
      response_type: 'code',
      client_id: CLIENT_ID,
      redirect_uri: `${window.location.origin}/auth/callback`,
      scope: 'openid email profile',
      state,
      code_challenge: base64Url,
      code_challenge_method: 'S256',
      provider,
    });
    if (setupOperatorToken) {
      params.set('setup_operator_token', setupOperatorToken);
    }

    window.location.href = `${ORIGIN_URI}/auth/authorize?${params.toString()}`;
  };

  const logout = () => {
    localStorage.removeItem('access_token');
    // As a service provider, signing out here alone is undone at once: the IdP still holds a session
    // and hands a new token back on the next visit. End that session too; the IdP returns only to an
    // address it lists, which this app's root is. The signed-in state is left as it is while the
    // page leaves: clearing it would render the sign-in redirect, whose navigation replaces this one.
    const { idpUri } = getRuntimeConfig();
    const idp = (idpUri || '').replace(/\/$/, '');
    if (idp && !idp.startsWith(window.location.origin)) {
      setLeaving('Signing out…');
      window.location.assign(`${idp}/logout?return=${encodeURIComponent(`${window.location.origin}/`)}`);
      return;
    }
    setToken(null);
    setUser(null);
    setIsAuthenticated(false);
  };

  // Sign in again once Origin has refused the session (`ORIGIN_SESSION_REQUIRED`). Origin may still
  // accept the stored token at `/auth/userinfo` after the session it was issued in has ended, so a
  // reload alone brings back the same token and the same refusal. The local session ends first:
  // the stored token, the held token for Mantle, and the cached person. Then a fresh sign-in starts
  // at Origin: on a service-provider deployment its sign-in page with `prompt=login`, which shows
  // the form rather than handing back the token Origin's page still holds; otherwise Origin's
  // authorization form. A live Origin session may still answer at once with a new token; the
  // stale one is gone either way.
  const signInAgain = () => {
    localStorage.removeItem('access_token');
    forgetMantleToken();
    setToken(null);
    setUser(null);
    setIsAuthenticated(false);
    setLeaving('Signing in again…');
    const { idpUri } = getRuntimeConfig();
    const idp = (idpUri || '').replace(/\/$/, '');
    if (idp && !idp.startsWith(window.location.origin)) {
      window.location.assign(originFreshSignInUrl());
      return;
    }
    void login('local');
  };

  // Force a fresh /userinfo fetch (e.g. after linking a provider)
  const refreshUser = useCallback(() => {
    const t = localStorage.getItem('access_token');
    if (!t) return;
    get<User>('/auth/userinfo')
      .then((res) => setUser(res))
      .catch(() => {/* silent */});
  }, []);

  // Start an OIDC provider link flow for the currently logged-in user.
  // Stores a 'linking_provider' marker in sessionStorage so AuthCallback
  // knows to call POST /auth/me/link-provider instead of /auth/token.
  const startLinkProvider = async (provider: string) => {
    const state = crypto.randomUUID();
    const codeVerifier = Array.from(crypto.getRandomValues(new Uint8Array(32)))
      .map(b => b.toString(16).padStart(2, '0'))
      .join('');
    const encoder = new TextEncoder();
    const digest = await crypto.subtle.digest('SHA-256', encoder.encode(codeVerifier));
    const base64Url = btoa(String.fromCharCode(...new Uint8Array(digest)))
      .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

    localStorage.setItem('pkce_state', state);
    localStorage.setItem('pkce_verifier', codeVerifier);
    // Signal AuthCallback to perform a link (not login) after the dance
    sessionStorage.setItem('linking_provider', provider);

    const params = new URLSearchParams({
      response_type: 'code',
      client_id: CLIENT_ID,
      redirect_uri: `${window.location.origin}/auth/callback`,
      scope: 'openid email profile',
      state,
      code_challenge: base64Url,
      code_challenge_method: 'S256',
      provider,
    });
    window.location.href = `${ORIGIN_URI}/auth/authorize?${params.toString()}`;
  };

  // Unlink the given provider from the current user's account.
  const unlinkProvider = async (provider: string) => {
    await del(`/auth/me/link-provider/${encodeURIComponent(provider)}`);
    refreshUser();
  };

  return (
    <AuthContext.Provider
      value={{ isAuthenticated, user, login, startLinkProvider, unlinkProvider, logout, signInAgain, loading, setAuthData, refreshUser }}
    >
      {leaving ? (
        <div className="flex h-screen items-center justify-center text-sm text-gray-500" role="status">
          {leaving}
        </div>
      ) : children}
    </AuthContext.Provider>
  );
};
