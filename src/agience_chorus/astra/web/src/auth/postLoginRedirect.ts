/**
 * Post-login redirect target.
 *
 * If an invite token is stashed in sessionStorage (by the claim page when
 * an unauthenticated user landed there), the user came here to accept an
 * invite --- send them back to the claim page, which asks them to accept it.
 *
 * Otherwise: home.
 */
const PENDING_INVITE_KEY = 'pending_invite_token';

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
 * Falls back to ``/`` (home) when no pending invite.
 */
export function postLoginRedirectTarget(): string {
  return popPendingInviteTarget() ?? '/';
}
