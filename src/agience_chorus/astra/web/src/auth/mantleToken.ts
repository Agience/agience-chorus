/**
 * Review 23, H1: the token the web app calls Mantle on, addressed to Mantle (`aud` `mantle`) and
 * issued in the person's Origin session (`POST /auth/me/authority/mantle-token`). Mantle refuses
 * the person's own Origin-audience token, which is kept for Origin's own routes alone, and this
 * one mints nothing at Origin.
 *
 * It is kept per signed-in person until shortly before it expires, and one request is shared by
 * every caller that asks while it is in flight (a page load asks from many places at once).
 *
 * With no Origin session for this browser, Origin answers 401. The app is then told
 * (`ORIGIN_SESSION_REQUIRED`, a window event the "sign in again" notice listens for), so the person
 * sees why, not an empty workspace.
 *
 * The browser's Origin session may be another person's (someone else signed in at Origin's page in
 * another tab). The web app never calls Mantle as them: it names the person it signed in
 * (`expect_sub`), Origin answers 409 for anyone else, and a token naming anyone else is refused
 * here too. Either way nothing is kept and the person is asked to sign in again.
 */
import { SessionTokenRefused, sessionToken } from './sessionToken'

/** The window event raised when Origin holds no session for this browser. */
export const ORIGIN_SESSION_REQUIRED = 'agience:origin-session-required'

let held: { subject: string; token: string; until: number } | null = null

/** The `sub` a JWT names, read without verifying it (Origin verified it; this only compares). */
function subOf(token: string): string | null {
  try {
    const part = token.split('.')[1]
    if (!part) return null
    const json = atob(part.replace(/-/g, '+').replace(/_/g, '/'))
    const sub = (JSON.parse(json) as { sub?: unknown }).sub
    return typeof sub === 'string' && sub ? sub : null
  } catch {
    return null
  }
}

function sessionRequired(): void {
  held = null
  window.dispatchEvent(new CustomEvent(ORIGIN_SESSION_REQUIRED))
}
let asking: { subject: string; pending: Promise<string> } | null = null

/** The token for Mantle while `subject` (the person's own token) is signed in. */
export async function mantleTokenFor(subject: string, originUri: string): Promise<string> {
  if (held && held.subject === subject && held.until > Date.now()) return held.token
  if (asking && asking.subject === subject) return asking.pending
  const pending = (async () => {
    try {
      const expected = subOf(subject)
      const { token, expiresIn } = await sessionToken(originUri, 'mantle-token',
                                                      expected ? { expect_sub: expected } : {})
      if (token === subject) throw new Error('Origin issued no token for Mantle')
      // A token for anyone else: refused as Origin's own 409 would be (the catch below).
      if (expected && subOf(token) !== expected) throw new SessionTokenRefused(409, 'mantle-token')
      held = { subject, token, until: Date.now() + Math.max(0, expiresIn - 30) * 1000 }
      return token
    } catch (err) {
      if (err instanceof SessionTokenRefused && (err.status === 401 || err.status === 409)) {
        sessionRequired()
      }
      throw err
    } finally {
      asking = null
    }
  })()
  asking = { subject, pending }
  return pending
}

/** Drops the held token for Mantle: the local session it was issued in has ended. */
export function forgetMantleToken(): void {
  held = null
  asking = null
}

export function resetMantleTokenForTests(): void {
  forgetMantleToken()
}
