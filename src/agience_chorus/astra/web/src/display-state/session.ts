/**
 * The viewer's sign-in, kept in this browser: the session token, and the PKCE pair a sign-in
 * holds between leaving for the identity provider and coming back.
 */

const TOKEN = 'access_token';
const PKCE_STATE = 'pkce_state';
const PKCE_VERIFIER = 'pkce_verifier';

/** The session token, or null when the viewer is signed out. */
export function readToken(): string | null {
  return localStorage.getItem(TOKEN);
}

export function saveToken(token: string): void {
  localStorage.setItem(TOKEN, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN);
}

/** Holds a sign-in's state and code verifier until the provider sends the viewer back. */
export function savePkce(state: string, verifier: string): void {
  localStorage.setItem(PKCE_STATE, state);
  localStorage.setItem(PKCE_VERIFIER, verifier);
}

export function pkceState(): string | null {
  return localStorage.getItem(PKCE_STATE);
}

export function pkceVerifier(): string | null {
  return localStorage.getItem(PKCE_VERIFIER);
}

export function clearPkce(): void {
  localStorage.removeItem(PKCE_STATE);
  localStorage.removeItem(PKCE_VERIFIER);
}
