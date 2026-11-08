/**
 * Post-login redirect target.
 *
 * If an invite token is stashed in sessionStorage (by the claim page when
 * an unauthenticated user landed there), the user came here to accept an
 * invite --- send them back to the claim page, which asks them to accept it.
 *
 * If a service provider was waiting on the sign-in page (`/login?redirect_uri=…&state=…`) when
 * the person left for Origin's sign-in, back to that page, which hands the new sign-in to it.
 *
 * Otherwise: home.
 */
const PENDING_INVITE_KEY = 'pending_invite_token';
const PENDING_SP_LOGIN_KEY = 'pending_sp_login';

/** Remember the sign-in page a waiting service provider sent the person to (`/login?...`). */
export function rememberSpLogin(path: string): void {
  if (!path.startsWith('/login?')) return;
  try { sessionStorage.setItem(PENDING_SP_LOGIN_KEY, path); } catch { /* storage unavailable */ }
}

function popSpLogin(): string | null {
  try {
    const path = sessionStorage.getItem(PENDING_SP_LOGIN_KEY);
    sessionStorage.removeItem(PENDING_SP_LOGIN_KEY);
    return path && path.startsWith('/login?') ? path : null;
  } catch {
    return null;
  }
}

export function popPendingInviteTarget(): string | null {
  try {
    const token = sessionStorage.getItem(PENDING_INVITE_KEY);
    if (!token) return null;
    // The claim page removes the key on a successful claim or a Cancel; until
    // then it stays, so a fresh login returns the user to the page to decide.
    return `/invite/${encodeURIComponent(token)}`;
  } catch {
    return null;
  }
}

/**
 * Redirect target for a newly-authenticated user.
 * Falls back to ``/`` (home) when no invite or service provider is waiting.
 */
export function postLoginRedirectTarget(): string {
  return popPendingInviteTarget() ?? popSpLogin() ?? '/';
}
