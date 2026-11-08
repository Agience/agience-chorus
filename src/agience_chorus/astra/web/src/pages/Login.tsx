/**
 * pages/Login.tsx
 *
 * The web app's sign-in page. Signing in, and creating an account, happen on Origin's own page;
 * this page sends the person there (`signInAtOrigin`), hands an existing sign-in back to a waiting
 * service provider (silent SSO), and, on a service-provider deployment, goes to the IdP's page.
 */

import React, { useEffect, useState, useCallback } from 'react'
import { FcGoogle } from 'react-icons/fc'
import { useNavigate, useLocation, Link } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { get } from '../api/api'
import { originSignInUrl } from '../auth/originSignIn'
import AuthLayout from '../components/layout/AuthLayout'
import { postLoginRedirectTarget, rememberSpLogin } from '../auth/postLoginRedirect'
import { getRuntimeConfig } from '../config/runtime'
import { issueSpState } from '../auth/spState'
import { isAllowedSpRedirect, tokenForSp } from '../auth/spRedirect'

type AuthProviderInfo = {
  name: string
  label: string
  type: string
}

type AuthProvidersResponse = {
  providers: AuthProviderInfo[]
  password: boolean
  otp: boolean
}

// Recent SP->IdP redirect timestamps, used to break an auth bounce loop.
const SP_ATTEMPTS_KEY = 'sp_login_attempts'

const Login: React.FC = () => {
  const { login, setAuthData, isAuthenticated } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [error, setError] = useState<string | null>(null)

  // Setup operator token — present when redirected from the setup wizard (Google-only)
  const setupOperatorToken = new URLSearchParams(location.search).get('setup_token') ?? undefined

  // SSO: an SP (e.g. lumen.agience.ai) redirected the user here to sign in via the
  // single Origin login screen. After any successful auth we return them to the SP
  // with the token in the URL fragment. redirect_uri must be on an allowed SP origin
  // (auth/spRedirect.ts), and only the IdP deployment hands tokens out — see `returnsTokenToSp`.
  const spRedirect = new URLSearchParams(location.search).get('redirect_uri') ?? undefined
  const spState = new URLSearchParams(location.search).get('state') ?? undefined

  // SP mode (the mirror of the above): when `idpUri` is configured this deployment is a
  // service provider — it has no login screen of its own. Deep-link to the single Origin
  // login page; it returns us the token in the URL fragment (AuthProvider consumes it).
  // Keeps the platform's login surface singular. Empty idpUri = we are that surface.
  const { idpUri: IDP_URI } = getRuntimeConfig()
  const isSp = Boolean(IDP_URI) && !IDP_URI.replace(/\/$/, '').startsWith(window.location.origin)
  // The token goes back to a waiting SP only from the IdP deployment, and only to an allowed SP
  // origin. An SP deployment never forwards its own token onward.
  const returnsTokenToSp = !isSp && Boolean(spRedirect) && isAllowedSpRedirect(spRedirect ?? '')
  const [spBlocked, setSpBlocked] = useState(false)
  useEffect(() => {
    if (!isSp || isAuthenticated) return
    // Loop guard. Origin has a session, so it answers every request by handing a token
    // straight back; if this app then rejects that token (audience mismatch, clock skew,
    // a revoked key), we'd bounce SP -> IdP -> SP forever and trap the user in a blank
    // redirect cycle. Cap the attempts and fail visibly instead.
    const now = Date.now()
    let attempts: number[] = []
    try {
      attempts = JSON.parse(sessionStorage.getItem(SP_ATTEMPTS_KEY) || '[]')
    } catch {
      attempts = []
    }
    attempts = attempts.filter((t) => now - t < 30_000)
    if (attempts.length >= 3) {
      console.warn('[Login] SP redirect loop detected — stopping')
      setSpBlocked(true)
      return
    }
    sessionStorage.setItem(SP_ATTEMPTS_KEY, JSON.stringify([...attempts, now]))
    const back = `${window.location.origin}/`
    const state = issueSpState()
    window.location.replace(
      `${IDP_URI.replace(/\/$/, '')}/login?redirect_uri=${encodeURIComponent(back)}` +
        `&state=${encodeURIComponent(state)}`,
    )
  }, [isSp, isAuthenticated, IDP_URI])

  // Strip consumed query params from the URL so they don't linger as a trailing "?"
  useEffect(() => {
    // Clean setup_token if present, and always strip a bare trailing "?"
    const params = new URLSearchParams(location.search)
    if (setupOperatorToken) params.delete('setup_token')
    const clean = params.toString()
    const target = `${location.pathname}${clean ? `?${clean}` : ''}`
    if (target !== `${location.pathname}${location.search}`) {
      window.history.replaceState(null, '', target)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const [providers, setProviders] = useState<AuthProviderInfo[]>([])
  const [providersReady, setProvidersReady] = useState(false)

  // Load providers on mount
  useEffect(() => {
    let mounted = true
    get<AuthProvidersResponse>('/auth/providers')
      .then((res) => {
        if (!mounted) return
        setProviders(res.providers || [])
        setProvidersReady(true)
      })
      .catch(() => {
        if (!mounted) return
        setProvidersReady(true) // proceed anyway
      })
    return () => { mounted = false }
  }, [])

  useEffect(() => {
    const params = new URLSearchParams(location.search)
    const msg = params.get('error')
    if (msg) {
      setError(decodeURIComponent(msg))
      // Clean the error param from the URL
      params.delete('error')
      const clean = params.toString()
      window.history.replaceState(null, '', `${location.pathname}${clean ? `?${clean}` : ''}`)
    }
  }, [location])

  // -- Finish: return the token to the SP (SSO) or set it locally (normal app login) --
  const finishLogin = useCallback((token: string) => {
    if (returnsTokenToSp && spRedirect) {
      // Establish the Origin session too, not just the SP's. Without this, signing in
      // through one SP leaves origin.agience.ai with no session, so the next SP would
      // prompt for credentials again. Persisting here is what makes one Origin session
      // serve mantle + my + lumen. (setAuthData isn't used: we navigate away
      // immediately, so its validation/state work would be torn down mid-flight.)
      try {
        localStorage.setItem('access_token', token)
      } catch {
        // Private mode / storage disabled — the SP still gets its token below.
      }
      const sep = spRedirect.includes('#') ? '&' : '#'
      // Review 8, R3: an SP other than this app gets a delegation Origin narrows to it, never the
      // person's full token; if Origin issues none, it gets nothing.
      tokenForSp(token, spRedirect, getRuntimeConfig().originUri)
        .then((spToken) => window.location.replace(
          `${spRedirect}${sep}access_token=${encodeURIComponent(spToken)}` +
          (spState ? `&state=${encodeURIComponent(spState)}` : '')
        ))
        .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      return
    }
    setAuthData(token)
  }, [returnsTokenToSp, spRedirect, spState, setAuthData])

  // Already signed in? An existing Origin session satisfies an SP's request with no
  // prompt — hand the token straight back (silent SSO). Only when there's no SP waiting
  // do we fall through into Origin's own app. Runs after finishLogin is defined.
  useEffect(() => {
    if (!isAuthenticated) return
    sessionStorage.removeItem(SP_ATTEMPTS_KEY) // a real session ends any bounce loop
    if (returnsTokenToSp) {
      const existing = localStorage.getItem('access_token')
      if (existing) {
        console.log('[Login] existing Origin session — returning token to the SP')
        finishLogin(existing)
        return
      }
    }
    navigate(postLoginRedirectTarget(), { replace: true })
  }, [isAuthenticated, navigate, returnsTokenToSp, finishLogin])

  // -- Sign in at Origin --
  // Credentials are typed only on Origin's own page (its `/auth/authorize` form: a password, a
  // mailed code, a new account, or a provider), and a sign-in there starts the person's Origin
  // session, which the web app's token for Mantle and every sharing change are made in. This page
  // never posts a password or a code itself. A service provider waiting on this page is returned
  // to once the sign-in comes back (`postLoginRedirect`).
  const signInAtOrigin = (provider: string = 'local') => {
    if (returnsTokenToSp) rememberSpLogin(`${location.pathname}${location.search}`)
    void login(provider, setupOperatorToken)
  }

  // A passkey ceremony happens only on Origin's own sign-in page (`auth/originSignIn.ts`): Origin
  // verifies the assertion against its own address.
  const handlePasskeyLogin = () => {
    window.location.assign(originSignInUrl())
  }

  // SP mode: never render a login form — we're bouncing to Origin. The only thing we
  // ever show here is the loop-guard escape hatch, so a failed handshake is visible
  // and recoverable rather than a blank page.
  if (isSp && !isAuthenticated) {
    if (!spBlocked) return null
    return (
      <AuthLayout>
        <div className="text-center space-y-4">
          <h1 className="text-lg font-semibold text-gray-800">Sign-in didn’t complete</h1>
          <p className="text-sm text-gray-500">
            We couldn’t establish a session with Origin. This usually clears on its own.
          </p>
          <button
            type="button"
            onClick={() => {
              sessionStorage.removeItem(SP_ATTEMPTS_KEY)
              localStorage.removeItem('access_token')
              setSpBlocked(false)
            }}
            className="w-full rounded-md bg-indigo-600 px-4 py-2 text-sm text-white hover:bg-indigo-700"
          >
            Try again
          </button>
        </div>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout
      footer={
        <p className="text-xs text-center text-gray-400 mt-6">
          <Link to="/terms" className="text-indigo-500 hover:underline">Terms</Link>
          {' · '}
          <Link to="/privacy" className="text-indigo-500 hover:underline">Privacy</Link>
        </p>
      }
    >
      {/* Heading */}
      <h1 className="text-center text-lg font-medium text-gray-800 mb-6">
        Welcome, let’s get you signed in
      </h1>

      {/* Error */}
      {error && (
        <div className="mb-4 bg-red-50 border border-red-200 text-red-600 px-4 py-2.5 rounded-lg text-sm" role="alert">
          {error}
        </div>
      )}

      <button
        type="button"
        onClick={() => signInAtOrigin('local')}
        className="w-full py-2.5 bg-gray-900 text-white rounded-lg font-medium hover:bg-gray-800 transition-colors text-sm"
      >
        Continue to sign in
      </button>
      <p className="text-xs text-center text-gray-500 mt-2">
        You sign in, or create an account, on Agience’s sign-in page.
      </p>
      <button
        type="button"
        onClick={handlePasskeyLogin}
        className="w-full text-sm text-gray-500 hover:text-indigo-600 hover:underline mt-3"
      >
        Sign in with a passkey
      </button>

      {providersReady && providers.length > 0 && (
        <>
          <div className="flex items-center gap-3 my-5 text-xs text-gray-400">
            <div className="flex-1 border-t border-gray-200" />
            <span>or sign in with</span>
            <div className="flex-1 border-t border-gray-200" />
          </div>
          <div className="space-y-2">
            {providers.map((p) => (
              <button
                key={p.name}
                onClick={() => signInAtOrigin(p.name)}
                className="w-full flex items-center justify-center gap-3 py-2.5 bg-white border border-gray-300 rounded-lg transition-all duration-200 shadow-sm hover:shadow-md hover:border-gray-400 hover:bg-gray-50 active:bg-gray-100 active:scale-[0.98] text-sm"
              >
                {p.name === 'google' ? <FcGoogle className="text-xl" /> : null}
                <span className="font-medium text-gray-600">{p.label}</span>
              </button>
            ))}
          </div>
        </>
      )}
    </AuthLayout>
  )
}

export default Login
