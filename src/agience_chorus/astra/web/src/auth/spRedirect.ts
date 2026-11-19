/**
 * Which service providers the IdP login page may return an access token to.
 *
 * An SP sends the user to `/login?redirect_uri=...`; after sign-in (or at once, when an Origin
 * session already exists) the page navigates to that URI with `#access_token=...`. The token goes
 * only to an exact origin on this list: this app's own origin, Origin's (`originUri`), and any the
 * deployment's runtime config names in `spOrigins`. A subdomain that merely ends in the platform domain is not on it.
 */

import { sessionToken } from './sessionToken'
import { getRuntimeConfig } from '../config/runtime'

function originOf(uri: string): string | null {
  try {
    return new URL(uri).origin
  } catch {
    return null
  }
}

/** This app's own origin and Origin's: their sign-ins keep the person's own token. */
function ownOrigins(): string[] {
  const own: string[] = []
  const origin = originOf(getRuntimeConfig().originUri)
  if (origin) own.push(origin)
  if (typeof window !== 'undefined') own.push(window.location.origin)
  return own
}

export function allowedSpOrigins(): string[] {
  return [...ownOrigins(), ...getRuntimeConfig().spOrigins]
}

/** True when `redirectUri` is an absolute URL on an allowed SP origin, carrying no credentials. */
export function isAllowedSpRedirect(
  redirectUri: string,
  origins: readonly string[] = allowedSpOrigins(),
): boolean {
  let url: URL
  try {
    url = new URL(redirectUri)
  } catch {
    return false
  }
  if (url.username || url.password) return false
  return origins.some((origin) => {
    try {
      return new URL(origin).origin === url.origin
    } catch {
      return false
    }
  })
}

/**
 * The audience a service provider's token is narrowed to, or null for the platform's own web app
 * and Origin (which keep the person's own token). Review 8, R3: any other SP (a persona page) gets
 * a delegation addressed to its own origin.
 */
export function spAudience(redirectUri: string): string | null {
  const origin = originOf(redirectUri)
  if (origin === null || ownOrigins().includes(origin)) return null
  return origin
}

/**
 * The token to hand a service provider. For the platform's own app, the person's token as is.
 * For any other, a delegation Origin narrows to that SP in the person's Origin session: short-lived,
 * its audience the SP's, never a platform-admin scope. If Origin will not issue one, this throws,
 * and the SP gets nothing; the person's full token never leaves for it.
 */
export async function tokenForSp(token: string, redirectUri: string,
                                 originUri: string): Promise<string> {
  const audience = spAudience(redirectUri)
  if (audience === null) return token
  // In the person's Origin session (review 23, H1): a bearer alone never narrows.
  const { token: narrowed } = await sessionToken(originUri, 'narrow', { audience })
  if (narrowed === token) throw new Error(`Origin issued no delegation for ${audience}`)
  return narrowed
}
