// @vitest-environment node
/**
 * Local development reaches Origin through the dev server (`originUri: '/'`). The proxy sends
 * Origin's own pages and their assets there, and leaves the web app its own routes: the sign-in
 * code comes back to the web app's `/auth/callback`, not to Origin's.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

function proxyRules(): RegExp[] {
  const path = process.env.DEV_PROXY_CONFIG || join(__dirname, '..', '..', '..', 'vite.config.ts')
  const src = readFileSync(path, 'utf8')
  const block = src.slice(src.indexOf('proxy: {'), src.indexOf('watch: {'))
  return [...block.matchAll(/^\s*'([^']+)':\s*\{\s*target/gm)].map(
    (m) => new RegExp(m[1].replace(/\\\\/g, '\\')))
}

const toOrigin = (path: string) => proxyRules().some((r) => r.test(path))

describe('the dev proxy', () => {
  it.each(['/login', '/login?redirect_uri=x', '/passkey', '/account', '/web/app.js',
           '/auth/token', '/auth/me/authority/mantle-token', '/setup/status', '/.well-known/jwks.json'])(
    'sends %s to Origin', (path) => {
      expect(toOrigin(path)).toBe(true)
    })

  it.each(['/auth/callback', '/auth/callback?code=c&state=s', '/', '/ws-1', '/setup',
           '/reset-password', '/verify-email', '/invite/t'])(
    'leaves %s to the web app', (path) => {
      expect(toOrigin(path)).toBe(false)
    })
})
