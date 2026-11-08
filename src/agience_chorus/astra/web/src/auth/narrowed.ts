/**
 * Review 11, H3: what the web app sends Crystal and the personas in place of the person's own
 * token: a delegation narrowed to one audience, the persona whose surface is called
 * (`/personas/{name}/...`), or Crystal for everything else Crystal does. Origin issues it in the
 * person's Origin session (review 23, H1: `POST /auth/me/authority/narrow`), never for a bearer.
 * A delegation is five minutes long and is kept per audience until it nears expiry. If Origin will
 * not issue one, the call is refused here; the person's full token never leaves for Crystal.
 */
import { sessionToken } from './sessionToken'

/** The audience a Crystal-bound call is narrowed to. */
export function crystalAudience(url: string): string {
  const m = /^\/personas\/([^/?#]+)\//.exec(url)
  return m ? decodeURIComponent(m[1]) : 'crystal'
}

const held = new Map<string, { subject: string; token: string; until: number }>()

/** The delegation Origin narrows to `audience` for the person signed in as `subject` (their own
 * token, which keys what is kept and is never sent). Throws when Origin issues none. */
export async function narrowedFor(subject: string, audience: string,
                                  originUri: string): Promise<string> {
  const kept = held.get(audience)
  const now = Date.now()
  if (kept && kept.subject === subject && kept.until > now) return kept.token
  const { token, expiresIn } = await sessionToken(originUri, 'narrow', { audience })
  if (token === subject) throw new Error(`Origin issued no delegation for ${audience}`)
  held.set(audience, { subject, token, until: now + Math.max(0, expiresIn - 30) * 1000 })
  return token
}

export function resetNarrowedForTests(): void {
  held.clear()
}
