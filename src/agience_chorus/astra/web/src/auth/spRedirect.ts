/**
 * Which service providers the IdP login page may return an access token to.
 *
 * An SP sends the user to `/login?redirect_uri=...`; after sign-in (or at once, when an Origin
 * session already exists) the page navigates to that URI with `#access_token=...`. The token goes
 * only to an exact origin on this list: the platform's own SPs plus any the deployment's runtime
 * config names in `spOrigins`. A subdomain that merely ends in the platform domain is not on it.
 */

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
