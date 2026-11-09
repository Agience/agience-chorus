/**
 * Says so when Origin holds no session for this browser (`ORIGIN_SESSION_REQUIRED`, raised when
 * Origin refuses the web app's token for Mantle with 401), and offers to sign in again at Origin.
 * Without the session no workspace can be read, so an empty app would only hide why. Signing in
 * again (`signInAgain` in the AuthProvider) ends the local session before it goes to Origin, so the
 * refused token is not brought back.
 */
import { useEffect, useState } from 'react'

import { ORIGIN_SESSION_REQUIRED } from '../../auth/mantleToken'
import { useAuth } from '../../hooks/useAuth'

export default function OriginSessionNotice() {
  const { signInAgain } = useAuth()
  const [needed, setNeeded] = useState(false)

  useEffect(() => {
    const onNeeded = () => setNeeded(true)
    window.addEventListener(ORIGIN_SESSION_REQUIRED, onNeeded)
    return () => window.removeEventListener(ORIGIN_SESSION_REQUIRED, onNeeded)
  }, [])

  if (!needed) return null
  return (
    <div className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/30">
      <div role="alertdialog" aria-labelledby="origin-session-title"
           className="max-w-sm w-full bg-white rounded-lg shadow-lg border p-6 text-center space-y-3">
        <h2 id="origin-session-title" className="text-lg font-semibold text-gray-900">
          Please sign in again
        </h2>
        <p className="text-sm text-gray-600">
          Your sign-in has ended, so your workspaces can’t be opened. Sign in again to continue.
        </p>
        <button type="button" onClick={signInAgain}
                className="w-full bg-gray-900 text-white py-2 px-4 rounded-md hover:bg-gray-800 text-sm">
          Sign in again
        </button>
      </div>
    </div>
  )
}
