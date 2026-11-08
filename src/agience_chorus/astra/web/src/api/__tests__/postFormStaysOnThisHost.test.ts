/**
 * The sign-in code is exchanged at Origin's `/auth/token` (`postForm`). In local development
 * Origin is reached through the dev server (`originUri: '/'`), so the address stays on this host.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

describe('postForm', () => {
  afterEach(() => {
    delete (window as { __AGIENCE_CONFIG__?: unknown }).__AGIENCE_CONFIG__
    vi.unstubAllGlobals()
    vi.resetModules()
  })

  it.each([['/', '/auth/token'], ['https://origin.example/', 'https://origin.example/auth/token']])(
    'with originUri %s posts to %s', async (originUri, expected) => {
      (window as { __AGIENCE_CONFIG__?: unknown }).__AGIENCE_CONFIG__ = { originUri }
      vi.resetModules()
      const urls: string[] = []
      vi.stubGlobal('fetch', vi.fn(async (u: string) => {
        urls.push(u)
        return new Response('{"access_token":"t"}', { status: 200 })
      }))
      const { postForm } = await import('../api')
      await postForm('/auth/token', new URLSearchParams({ a: 'b' }))
      expect(urls).toEqual([expected])
    })
})
