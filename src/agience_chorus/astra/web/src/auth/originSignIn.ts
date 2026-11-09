// auth/originSignIn.ts
//
// Where a passkey sign-in happens: on Origin's own sign-in page, never in this web app (review 7,
// F1). Origin verifies every WebAuthn assertion against its own address, so a ceremony run here
// could not complete, and no page this app, or Mantle, serves is one Origin trusts for one. The
// person is sent to Origin's `/login`, which returns the token in the URL fragment with the `state`
// this browser issued (`spState`), as any service-provider sign-in does.

import { getRuntimeConfig } from '../config/runtime';
import { issueSpState } from './spState';

function loginUrl(): URL {
  const { originUri, idpUri } = getRuntimeConfig();
  const base = new URL((idpUri || originUri).replace(/\/$/, '') + '/login', window.location.href);
  base.searchParams.set('redirect_uri', `${window.location.origin}/`);
  base.searchParams.set('state', issueSpState());
  return base;
}

export function originSignInUrl(loginHint?: string): string {
  const base = loginUrl();
  if (loginHint) base.searchParams.set('login_hint', loginHint);
  return base.toString();
}

/** Origin's sign-in page asked for a fresh sign-in (`prompt=login`, the OIDC way). Without it,
 *  Origin's page hands back whatever token it still holds (silent SSO), even one whose Origin
 *  session has ended, and "sign in again" would return that same token here. */
export function originFreshSignInUrl(): string {
  const base = loginUrl();
  base.searchParams.set('prompt', 'login');
  return base.toString();
}
