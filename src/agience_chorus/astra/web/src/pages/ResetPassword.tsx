/**
 * pages/ResetPassword.tsx
 *
 * Two-in-one password reset:
 *   - No `?token=`  → "forgot password" form: enter email → POST /auth/password/reset-request
 *   - With `?token=` → set a new password → POST /auth/password/reset-confirm
 *
 * The request side always shows the same confirmation (never reveals whether an
 * account exists). The server enforces the password policy; we surface its error.
 */

import React, { useState } from 'react'
import { useNavigate, useSearchParams, Link } from 'react-router-dom'
import { post } from '../api/api'
import { toast } from 'sonner'
import AuthLayout from '../components/layout/AuthLayout'

function errorDetail(err: unknown, fallback: string): string {
  const e = err as { response?: { data?: { detail?: string } }; message?: string }
  return e?.response?.data?.detail || fallback
}

const ResetPassword: React.FC = () => {
  const [params] = useSearchParams()
  const token = params.get('token') || ''
  const navigate = useNavigate()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const requestReset = async () => {
    if (!email) return
    setSubmitting(true)
    setError(null)
    try {
      await post('/auth/password/reset-request', { email })
    } catch {
      // Intentionally swallow — same UX whether or not the account exists.
    } finally {
      setSent(true)
      setSubmitting(false)
    }
  }

  const confirmReset = async () => {
    setError(null)
    if (!password) return
    if (password !== confirm) {
      setError('Passwords do not match.')
      return
    }
    setSubmitting(true)
    try {
      await post('/auth/password/reset-confirm', { token, new_password: password })
      toast.success('Password updated — you can sign in now.')
      navigate('/login', { replace: true })
    } catch (err) {
      setError(errorDetail(err, 'This reset link is invalid or has expired. Request a new one.'))
    } finally {
      setSubmitting(false)
    }
  }

  const footer = (
    <p className="text-xs text-center text-gray-400 mt-6">
      <Link to="/login" className="text-indigo-500 hover:underline">Back to sign in</Link>
    </p>
  )

  // --- Request phase (no token) ---
  if (!token) {
    return (
      <AuthLayout footer={footer}>
        <h1 className="text-center text-lg font-medium text-gray-800 mb-6">Reset your password</h1>
        {sent ? (
          <div className="bg-green-50 border border-green-200 text-green-700 px-4 py-3 rounded-lg text-sm text-center">
            If an account exists for that email, we've sent a reset link. Check your inbox.
          </div>
        ) : (
          <form onSubmit={(e) => { e.preventDefault(); requestReset() }} className="space-y-4">
            <p className="text-sm text-gray-500">Enter your email and we'll send you a link to reset your password.</p>
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
              {submitting ? 'Sending...' : 'Send reset link'}
            </button>
          </form>
        )}
      </AuthLayout>
    )
  }

  // --- Confirm phase (token present) ---
  return (
    <AuthLayout footer={footer}>
      <h1 className="text-center text-lg font-medium text-gray-800 mb-6">Choose a new password</h1>
      {error && (
        <div className="mb-4 bg-red-50 border border-red-200 text-red-600 px-4 py-2.5 rounded-lg text-sm" role="alert">
          {error}
        </div>
      )}
      <form onSubmit={(e) => { e.preventDefault(); confirmReset() }} className="space-y-4">
        <div className="space-y-1.5">
          <label htmlFor="new-password" className="block text-sm font-medium text-gray-700">New password</label>
          <input
            id="new-password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoFocus
            autoComplete="new-password"
            disabled={submitting}
            className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-400 focus:border-transparent text-sm"
          />
        </div>
        <div className="space-y-1.5">
          <label htmlFor="confirm-password" className="block text-sm font-medium text-gray-700">Confirm password</label>
          <input
            id="confirm-password"
            type="password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            autoComplete="new-password"
            disabled={submitting}
            className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-400 focus:border-transparent text-sm"
          />
        </div>
        <button
          type="submit"
          disabled={!password || !confirm || submitting}
          className="w-full py-2.5 bg-gray-900 text-white rounded-lg font-medium hover:bg-gray-800 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-sm"
        >
          {submitting ? 'Updating...' : 'Update password'}
        </button>
      </form>
    </AuthLayout>
  )
}

export default ResetPassword
