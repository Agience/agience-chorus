/**
 * Which service providers the IdP login page may return an access token to.
 *
 * An SP sends the user to `/login?redirect_uri=...`; after sign-in (or at once, when an Origin
 * session already exists) the page navigates to that URI with `#access_token=...`. The token goes
 * only to an exact origin on this list: the platform's own SPs plus any the deployment's runtime
 * config names in `spOrigins`. A subdomain that merely ends in the platform domain is not on it.
 */

import { sessionToken } from './sessionToken'
import { getRuntimeConfig } from '../config/runtime'

/** The platform's service providers, and Origin itself. */
export const KNOWN_SP_ORIGINS: readonly string[] = [
  'https://origin.agience.ai',
  'https://my.agience.ai',
  'https://lumen.agience.ai',
]

export function allowedSpOrigins(): string[] {
  return [...KNOWN_SP_ORIGINS, ...getRuntimeConfig().spOrigins]
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
 * and Origin (which keep the person's own token). Review 8, R3: Ember (lumen.agience.ai) gets a
 * delegation addressed to `ember`; any other SP (a persona page) one addressed to its own origin.
 */
export function spAudience(redirectUri: string): string | null {
  let origin: string
  try {
    origin = new URL(redirectUri).origin
  } catch {
    return null
  }
  if (origin === 'https://my.agience.ai' || origin === 'https://origin.agience.ai') return null
  if (typeof window !== 'undefined' && origin === window.location.origin) return null
  if (origin === 'https://lumen.agience.ai') return 'ember'
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
