/**
 * pages/VerifyEmail.tsx
 *
 * Landing page for the email-verification link.
 *   - With `?token=` → POST /auth/email/verify-confirm. On success the response
 *     carries an access token (magic-link sign-in) → store it and go to the app.
 *   - On failure / no token → offer to resend via POST /auth/email/verify-request.
 */

import React, { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams, Link } from 'react-router-dom'
import { post } from '../api/api'
import { useAuth } from '../hooks/useAuth'
import AuthLayout from '../components/layout/AuthLayout'

function errorDetail(err: unknown, fallback: string): string {
  const e = err as { response?: { data?: { detail?: string } } }
  return e?.response?.data?.detail || fallback
}

type Phase = 'verifying' | 'error' | 'resend' | 'sent'

const VerifyEmail: React.FC = () => {
  const [params] = useSearchParams()
  const token = params.get('token') || ''
  const navigate = useNavigate()
  const { setAuthData } = useAuth()

  const [phase, setPhase] = useState<Phase>(
    token ? 'verifying' : params.get('sent') ? 'sent' : 'resend'
  )
  const [error, setError] = useState<string | null>(null)
  const [email, setEmail] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const ran = useRef(false)

  useEffect(() => {
    if (!token || ran.current) return
    ran.current = true
    post<{ access_token?: string }>('/auth/email/verify-confirm', { token })
      .then((res) => {
        if (res.access_token) {
          setAuthData(res.access_token)
          navigate('/', { replace: true })
        } else {
          navigate('/login', { replace: true })
        }
      })
      .catch((err) => {
        setError(errorDetail(err, 'This verification link is invalid or has expired.'))
        setPhase('error')
      })
  }, [token, navigate, setAuthData])

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
