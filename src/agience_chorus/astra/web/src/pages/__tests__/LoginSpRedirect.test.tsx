/**
 * Silent SSO: a signed-in user who lands on the IdP's /login with `?redirect_uri=` is sent back to
 * that URI with `#access_token=`. The token must go only to an allowed SP origin, and never from
 * an SP deployment.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import Login from '../Login';
import { isAllowedSpRedirect, KNOWN_SP_ORIGINS } from '../../auth/spRedirect';

vi.mock('../../hooks/useAuth', () => ({
  useAuth: () => ({ login: vi.fn(), setAuthData: vi.fn(), isAuthenticated: true }),
}));
vi.mock('../../api/api', () => ({
  get: vi.fn(async () => ({ providers: [], password: true, otp: false })),
  post: vi.fn(),
}));
vi.mock('../../api/setup', () => ({
  getPasskeyLoginOptions: vi.fn(),
  completePasskeyLogin: vi.fn(),
  requestOTP: vi.fn(),
  verifyOTP: vi.fn(),
}));
vi.mock('../../components/layout/AuthLayout', () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock('../../components/auth/CreateAccountForm', () => ({ default: () => null }));

const HANDOFF_LOG = '[Login] existing Origin session — returning token to the SP';

function renderLogin(redirectUri: string) {
  return render(
    <MemoryRouter initialEntries={[`/login?redirect_uri=${encodeURIComponent(redirectUri)}&state=s1`]}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<div>HOME</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('Login silent SSO hand-off', () => {
  let logSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    localStorage.setItem('access_token', 'origin-session-token');
    delete (window as { __AGIENCE_CONFIG__?: unknown }).__AGIENCE_CONFIG__;
    logSpy = vi.spyOn(console, 'log').mockImplementation(() => {});
  });

  afterEach(() => {
    logSpy.mockRestore();
    localStorage.clear();
    sessionStorage.clear();
    delete (window as { __AGIENCE_CONFIG__?: unknown }).__AGIENCE_CONFIG__;
  });

  it.each([
    'https://evil.agience.ai/',
    'https://agience.ai/',
    'https://my.agience.ai.evil.com/',
    'https://attacker@my.agience.ai/',
    'http://my.agience.ai/',
  ])('does not hand the token to %s', async (redirectUri) => {
    renderLogin(redirectUri);
    expect(await screen.findByText('HOME')).toBeInTheDocument();
    expect(logSpy).not.toHaveBeenCalledWith(HANDOFF_LOG);
  });

  it('hands the token back to a known SP origin', async () => {
    renderLogin('https://my.agience.ai/');
    await waitFor(() => expect(logSpy).toHaveBeenCalledWith(HANDOFF_LOG));
    expect(screen.queryByText('HOME')).toBeNull();
  });

  it('never hands a token onward from an SP deployment', async () => {
    (window as { __AGIENCE_CONFIG__?: unknown }).__AGIENCE_CONFIG__ = {
      idpUri: 'https://origin.agience.ai',
    };
    renderLogin('https://my.agience.ai/');
    expect(await screen.findByText('HOME')).toBeInTheDocument();
    expect(logSpy).not.toHaveBeenCalledWith(HANDOFF_LOG);
  });
});

describe('isAllowedSpRedirect', () => {
  it('accepts every known SP origin, with or without a path', () => {
    for (const origin of KNOWN_SP_ORIGINS) {
      expect(isAllowedSpRedirect(`${origin}/`)).toBe(true);
      expect(isAllowedSpRedirect(`${origin}/app?x=1`)).toBe(true);
    }
  });

  it('accepts an origin the runtime config adds', () => {
    (window as { __AGIENCE_CONFIG__?: unknown }).__AGIENCE_CONFIG__ = {
      spOrigins: ['https://sp.example.com'],
    };
    try {
      expect(isAllowedSpRedirect('https://sp.example.com/')).toBe(true);
    } finally {
      delete (window as { __AGIENCE_CONFIG__?: unknown }).__AGIENCE_CONFIG__;
    }
  });

  it.each([
    'https://evil.agience.ai/',
    'https://my.agience.ai.evil.com/',
    'https://my.agience.ai:8443/',
    'https://user:pw@my.agience.ai/',
    'http://my.agience.ai/',
    'javascript:alert(1)',
    '/relative',
    '',
  ])('rejects %j', (redirectUri) => {
    expect(isAllowedSpRedirect(redirectUri)).toBe(false);
  });
});
