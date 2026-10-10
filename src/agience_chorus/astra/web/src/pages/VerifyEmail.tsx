/**
 * pages/VerifyEmail.tsx
 *
 * Landing page for the email-verification link.
 *   - With `?token=` → POST /auth/email/verify-confirm. Origin signs the browser in (returns an
 *     access token) only when the request carries the nonce the link was minted for; this page
 *     sends none, so the usual answer is `{"verified": true}` with no token → "Email verified —
 *     sign in". A token, when one does come back, is stored and the app opens.
 *   - An account with a password answers `{"password_required": true}` and nothing changes: Origin
 *     confirms it only with that password, since whoever registered the address may not be whoever
 *     holds the mailbox. The page asks for it. Whoever holds the mailbox but did not create the
 *     account presses "I didn't create this account" (`disown`): the address is confirmed as theirs,
 *     the password someone else chose is dropped (`password_cleared`), and they sign in with a code.
 *   - A link redeemed a second time answers 400 with `error: "already_verified"` → shown as
 *     "already verified — sign in", not as a failure.
 *   - On any other failure / no token → offer to resend via POST /auth/email/verify-request.
 */

import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams, Link } from 'react-router-dom'
import { post } from '../api/api'
import { useAuth } from '../hooks/useAuth'
import AuthLayout from '../components/layout/AuthLayout'

function errorDetail(err: unknown, fallback: string): string {
  const e = err as { response?: { data?: { detail?: string } } }
  return e?.response?.data?.detail || fallback
}

function isAlreadyVerified(err: unknown): boolean {
  const e = err as { response?: { data?: { error?: string } } }
  return e?.response?.data?.error === 'already_verified'
}

function status(err: unknown): number | undefined {
  const e = err as { response?: { status?: number } }
  return e?.response?.status
}

type Phase =
  | 'verifying' | 'password' | 'verified' | 'disowned' | 'already-verified' | 'error' | 'resend' | 'sent'

type Confirmed = { access_token?: string; password_required?: boolean; password_cleared?: boolean }

const VerifyEmail: React.FC = () => {
  const [params] = useSearchParams()
  // Read once and kept in state: the password and disown steps send it again after the address
  // bar has been cleared of it.
  const [token] = useState(() => params.get('token') || '')
  const navigate = useNavigate()
  const { setAuthData } = useAuth()

  const [phase, setPhase] = useState<Phase>(
    token ? 'verifying' : params.get('sent') ? 'sent' : 'resend'
  )
  const [error, setError] = useState<string | null>(null)
  const [email, setEmail] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [password, setPassword] = useState('')
  const [passwordError, setPasswordError] = useState<string | null>(null)
  const [disownArmed, setDisownArmed] = useState(false)
  const ran = useRef(false)

  const settle = useCallback((res: Confirmed) => {
    if (res.password_required) {
      setPhase('password')
    } else if (res.password_cleared) {
      setPhase('disowned')
    } else if (res.access_token) {
      setAuthData(res.access_token)
      navigate('/', { replace: true })
    } else {
      setPhase('verified')
    }
  }, [navigate, setAuthData])

  const fail = useCallback((err: unknown) => {
    if (isAlreadyVerified(err)) {
      setPhase('already-verified')
      return
    }
    setError(errorDetail(err, 'This verification link is invalid or has expired.'))
    setPhase('error')
  }, [])

  // The verification token leaves the address bar as soon as it is read, so it does not stay in
  // history, get bookmarked, or travel in a Referer.
  useEffect(() => {
    const url = new URL(window.location.href)
    if (!url.searchParams.has('token')) return
    url.searchParams.delete('token')
    window.history.replaceState(window.history.state, '', `${url.pathname}${url.search}${url.hash}`)
  }, [])

  useEffect(() => {
    if (!token || ran.current) return
    ran.current = true
    post<Confirmed>('/auth/email/verify-confirm', { token }).then(settle).catch(fail)
  }, [token, settle, fail])

  const confirmWithPassword = async () => {
    setSubmitting(true)
    setPasswordError(null)
    try {
      settle(await post<Confirmed>('/auth/email/verify-confirm', { token, password }))
    } catch (err) {
      const s = status(err)
      // A wrong password, a throttled one, or a busy server: the prompt stays and says why.
      if (s === 401 || s === 429 || s === 503) {
        setPasswordError(errorDetail(err, "That password doesn't match this account."))
      } else {
        fail(err)
      }
    } finally {
      setSubmitting(false)
    }
  }

  // Two clicks, so neither a slip nor a mail scanner that clicks through a page drops a password.
  const disown = async () => {
    if (!disownArmed) {
      setDisownArmed(true)
      return
    }
    setSubmitting(true)
    try {
      settle(await post<Confirmed>('/auth/email/verify-confirm', { token, disown: true }))
    } catch (err) {
      fail(err)
    } finally {
      setSubmitting(false)
    }
  }

  const resend = async () => {
    if (!email) return
    setSubmitting(true)
    try {
      await post('/auth/email/verify-request', { email })
    } catch {
      // Same UX regardless of whether the account exists.
    } finally {
      setPhase('sent')
      setSubmitting(false)
    }
  }

  const footer = (
    <p className="text-xs text-center text-gray-400 mt-6">
      <Link to="/login" className="text-indigo-500 hover:underline">Back to sign in</Link>
    </p>
  )

  return (
    <AuthLayout footer={footer}>
      <h1 className="text-center text-lg font-medium text-gray-800 mb-6">Verify your email</h1>

      {phase === 'verifying' && (
        <p className="text-sm text-gray-500 text-center">Verifying your email…</p>
      )}

      {phase === 'password' && (
        <form onSubmit={(e) => { e.preventDefault(); confirmWithPassword() }} className="space-y-4">
          <p className="text-sm text-gray-500">
            Enter the password you chose for this account to confirm your email.
          </p>
          {passwordError && (
            <div className="bg-red-50 border border-red-200 text-red-600 px-4 py-2.5 rounded-lg text-sm" role="alert">
              {passwordError}
            </div>
          )}
          <input
            type="password"
            aria-label="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoFocus
            autoComplete="current-password"
            disabled={submitting}
            className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-400 focus:border-transparent text-sm"
          />
          <button
            type="submit"
            disabled={!password || submitting}
            className="w-full py-2.5 bg-gray-900 text-white rounded-lg font-medium hover:bg-gray-800 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-sm"
          >
            {submitting ? 'Confirming...' : 'Confirm my email'}
          </button>
          {disownArmed && (
            <p className="text-sm text-gray-500">
              If you did not create this account, it becomes yours: the address is confirmed and the
              password someone else chose is removed. You then sign in with an emailed code.
            </p>
          )}
          <button
            type="button"
            onClick={disown}
            disabled={submitting}
            className="w-full text-sm text-indigo-500 hover:underline disabled:opacity-50"
          >
            {disownArmed ? 'Remove the password and confirm this email as mine' : "I didn't create this account"}
          </button>
        </form>
      )}

      {phase === 'disowned' && (
        <div className="space-y-4">
          <div className="bg-green-50 border border-green-200 text-green-700 px-4 py-3 rounded-lg text-sm text-center" role="status">
            Email confirmed as yours. The password set when this account was created was removed — sign in with an emailed code.
          </div>
          <Link
            to="/login"
            className="block w-full py-2.5 bg-gray-900 text-white rounded-lg font-medium hover:bg-gray-800 transition-colors text-sm text-center"
          >
            Sign in
          </Link>
        </div>
      )}

      {(phase === 'verified' || phase === 'already-verified') && (
        <div className="space-y-4">
          <div className="bg-green-50 border border-green-200 text-green-700 px-4 py-3 rounded-lg text-sm text-center" role="status">
            {phase === 'verified' ? 'Email verified — sign in to continue.' : 'This email is already verified — sign in.'}
          </div>
          <Link
            to="/login"
            className="block w-full py-2.5 bg-gray-900 text-white rounded-lg font-medium hover:bg-gray-800 transition-colors text-sm text-center"
          >
            Sign in
          </Link>
        </div>
      )}

      {phase === 'error' && (
        <div className="space-y-4">
          <div className="bg-red-50 border border-red-200 text-red-600 px-4 py-2.5 rounded-lg text-sm" role="alert">
            {error}
          </div>
          <button
            onClick={() => setPhase('resend')}
            className="w-full py-2.5 bg-gray-900 text-white rounded-lg font-medium hover:bg-gray-800 transition-colors text-sm"
          >
            Send a new link
          </button>
        </div>
      )}

      {phase === 'resend' && (
        <form onSubmit={(e) => { e.preventDefault(); resend() }} className="space-y-4">
          <p className="text-sm text-gray-500">Enter your email and we'll send a new verification link.</p>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            autoFocus
            autoComplete="email"
            disabled={submitting}
            className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-400 focus:border-transparent text-sm"
          />
          <button
            type="submit"
            disabled={!email || submitting}
            className="w-full py-2.5 bg-gray-900 text-white rounded-lg font-medium hover:bg-gray-800 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-sm"
          >
            {submitting ? 'Sending...' : 'Send verification link'}
          </button>
        </form>
      )}

      {phase === 'sent' && (
        <div className="bg-green-50 border border-green-200 text-green-700 px-4 py-3 rounded-lg text-sm text-center">
          If an account exists for that email, we've sent a new verification link. Check your inbox.
        </div>
      )}
    </AuthLayout>
  )
}

export default VerifyEmail
