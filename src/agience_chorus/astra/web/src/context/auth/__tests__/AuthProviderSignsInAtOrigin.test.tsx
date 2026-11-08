/**
 * Signing in goes to Origin's `/auth/authorize`. Local development reaches Origin through the dev
 * server (`originUri: '/'`), so the address must stay on this host: `//auth/authorize` would name
 * a host called "auth".
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import { useContext, useEffect } from 'react'

describe('signing in at Origin', () => {
  afterEach(() => {
    delete (window as { __AGIENCE_CONFIG__?: unknown }).__AGIENCE_CONFIG__
    vi.unstubAllGlobals()
    vi.resetModules()
  })

  it.each([['/', 'http://localhost:3000/auth/authorize'],
           ['https://origin.example/', 'https://origin.example/auth/authorize']])(
    'with originUri %s, goes to %s', async (originUri, expected) => {
      (window as { __AGIENCE_CONFIG__?: unknown }).__AGIENCE_CONFIG__ = { originUri }
      vi.resetModules()
      const { AuthProvider } = await import('../AuthProvider')
      const { AuthContext } = await import('../AuthContext')
      const assigned: string[] = []
      vi.stubGlobal('location', { ...window.location, origin: 'http://localhost:3000',
        href: 'http://localhost:3000/login',
        set href(v: string) { assigned.push(v) } } as unknown as Location)
      function Go() {
        const ctx = useContext(AuthContext)
        useEffect(() => { void ctx?.login('local') }, [ctx])
        return null
      }
      render(<AuthProvider><Go /></AuthProvider>)
      await waitFor(() => expect(assigned.length).toBeGreaterThan(0))
      const url = new URL(assigned[0], 'http://localhost:3000/login')
      expect(`${url.origin}${url.pathname}`).toBe(expected)
      expect(url.searchParams.get('provider')).toBe('local')
    })
})

// 2026-11-08, the local check: the invite page's "Sign in to continue" called `login()`, which
// asked Origin for Google, which this node does not have. With no provider named, Origin's own
// chooser is shown: every method the node has.
describe('signing in with no provider named', () => {
  afterEach(() => {
    delete (window as { __AGIENCE_CONFIG__?: unknown }).__AGIENCE_CONFIG__
    vi.unstubAllGlobals()
    vi.resetModules()
  })

  it('asks Origin for its own chooser', async () => {
    (window as { __AGIENCE_CONFIG__?: unknown }).__AGIENCE_CONFIG__ = { originUri: '/' }
    vi.resetModules()
    const { AuthProvider } = await import('../AuthProvider')
    const { AuthContext } = await import('../AuthContext')
    const assigned: string[] = []
    vi.stubGlobal('location', { ...window.location, origin: 'http://localhost:3000',
      href: 'http://localhost:3000/invite/t',
      set href(v: string) { assigned.push(v) } } as unknown as Location)
    function Go() {
      const ctx = useContext(AuthContext)
      useEffect(() => { void ctx?.login() }, [ctx])
      return null
    }
    render(<AuthProvider><Go /></AuthProvider>)
    await waitFor(() => expect(assigned.length).toBeGreaterThan(0))
    expect(new URL(assigned[0], 'http://localhost:3000/').searchParams.get('provider')).toBe('local')
  })
})
