/**
 * Review 23, H1: every token the web app derives from the person's sign-in is issued in the
 * person's Origin session, never by showing Origin a bearer. Mantle holds what the web app sends
 * it, so a token endpoint that narrowed any bearer let Mantle mint a delegation for any persona.
 *
 * Each call carries the Origin session cookie (`credentials: 'include'`) and the `X-Origin-Session`
 * header Origin's CSRF check requires, as the authority calls do (`api/authority.ts`). The person's
 * own token is not in the request.
 */

export type SessionToken = { token: string; expiresIn: number }

/** Origin refused a session route; `status` 401 means it holds no session for this browser. */
export class SessionTokenRefused extends Error {
  constructor(readonly status: number, route: string) {
    super(`Origin issued no token at ${route} (${status})`)
    this.name = 'SessionTokenRefused'
  }
}

/** POST a session route under `/auth/me/authority/`; the token Origin issues, or a throw. */
export async function sessionToken(originUri: string, route: string,
                                   body: Record<string, unknown> = {}): Promise<SessionToken> {
  const r = await fetch(`${originUri.replace(/\/$/, '')}/auth/me/authority/${route}`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', 'X-Origin-Session': '1' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new SessionTokenRefused(r.status, route)
  const out = (await r.json()) as { access_token?: string; expires_in?: number }
  if (!out.access_token) throw new Error(`Origin issued no token at ${route}`)
  return { token: out.access_token, expiresIn: Number(out.expires_in ?? 300) }
}
