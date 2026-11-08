import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { get, post } from '../api/api';
import { claimInvite } from '../api/artifacts';
import { inviteContext } from '../api/authority';
import { SessionTokenRefused } from '../auth/sessionToken';
import { toast } from 'sonner';

/** What an invite grants, as Origin reads it for this person (round 13), without claiming it. */
type InviteDetails = {
  valid?: boolean;
  identity_mismatch?: boolean;
  /** The signed-in address is not verified, which an invite needs before it can match. */
  unverified?: boolean;
  resource_id?: string;
  actions?: string[];
};

/**
 * /invite/:token -- public invite claim page.
 *
 * The token in the link is a secret: it goes to Origin only, in the person's Origin session, never
 * to Mantle (round 13). Origin mailed the link to one address and takes the claim only from a
 * person signed in with that verified address.
 *
 * - Pre-auth: show only "You've been invited to collaborate." No inviter
 *   name, no resource name, no email hint.
 * - Post-auth: show what Origin's invite context returns without claiming
 *   (the resource id and what it grants; or that the invite is addressed to
 *   someone else) and claim only on an explicit Accept click. Opening the
 *   link never claims anything by itself.
 */
/** How long the page waits for Mantle to open a claimed item, and how often it asks. Mantle reads
 *  Origin's feed every 15 s; the wait covers two passes. */
const ACCESS_WAIT_MS = 40_000;
const ACCESS_POLL_MS = 1_000;

/** `'open'` once Mantle opens `resourceId` for this person, or after `ACCESS_WAIT_MS` (the item's
 *  page then says what it can); `'stopped'` when `stopped()` turns true (the page was left) or
 *  Origin holds no session for this browser, where asking again would only be refused again. */
async function waitForAccess(resourceId: string, stopped: () => boolean): Promise<'open' | 'stopped' | 'no_session'> {
  const until = Date.now() + ACCESS_WAIT_MS;
  for (;;) {
    if (stopped()) return 'stopped';
    try {
      await get(`/artifacts/${encodeURIComponent(resourceId)}`);
      return 'open';
    } catch (err) {
      if (err instanceof SessionTokenRefused) return 'no_session';
      if (Date.now() >= until) return 'open';
      await new Promise((r) => setTimeout(r, ACCESS_POLL_MS));
    }
  }
}

export default function InviteClaimPage() {
  const { token } = useParams<{ token: string }>();
  const navigate = useNavigate();
  const { isAuthenticated, loading: authLoading, login, user } = useAuth();

  const [status, setStatus] = useState<'loading' | 'awaiting_auth' | 'confirm' | 'claiming' | 'setting_up' | 'success' | 'error'>('loading');
  const [verifySent, setVerifySent] = useState(false);
  const [message, setMessage] = useState('');
  const [details, setDetails] = useState<InviteDetails | null>(null);

  const claimedRef = useRef(false);
  // Set when the page is left, so a wait for access in flight stops asking Mantle.
  const leftRef = useRef(false);
  useEffect(() => {
    leftRef.current = false;
    return () => { leftRef.current = true; };
  }, []);
  const detailsRequestedRef = useRef(false);

  // Pre-auth: nothing is read; the person signs in first, at Origin.
  useEffect(() => {
    if (!token) {
      setStatus('error');
      setMessage('Invalid invite link.');
      return;
    }
    if (!isAuthenticated && !authLoading) setStatus('awaiting_auth');
  }, [token, isAuthenticated, authLoading]);

  // Claim, only from the Accept button.
  const doClaim = useCallback(async () => {
    if (!token || claimedRef.current) return;
    claimedRef.current = true;
    setStatus('claiming');

    try {
      const result = await claimInvite(token);
      sessionStorage.removeItem('pending_invite_token');
      toast.success('Invite accepted!');

      const resourceId = result?.resource_id;
      if (!resourceId) {
        setStatus('success');
        setTimeout(() => navigate('/', { replace: true }), 1200);
        return;
      }
      // Origin made the grant; Mantle applies it from Origin's feed on its next pass. Until then
      // the item would be refused, so the page waits for Mantle to open it, saying so.
      setStatus('setting_up');
      const access = await waitForAccess(resourceId, () => leftRef.current);
      if (access === 'stopped') return;
      if (access === 'no_session') {
        setStatus('error');
        setMessage('The invite is accepted. Sign in again to open it.');
        return;
      }
      setStatus('success');
      navigate(`/${resourceId}`, { replace: true });
    } catch (err: unknown) {
      setStatus('error');
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'Failed to accept invite.';
      setMessage(detail);
      claimedRef.current = false;
    }
  }, [token, navigate]);

  // Once signed in, read what the invite grants (a read; nothing is claimed) and ask.
  useEffect(() => {
    if (!isAuthenticated || authLoading || !token || status === 'error' || detailsRequestedRef.current) return;
    detailsRequestedRef.current = true;
    inviteContext(token)
      .then((c) => {
        if (c?.state && c.state !== 'active') {
          setStatus('error');
          setMessage('This invite is no longer valid.');
          return;
        }
        setDetails({ valid: true, identity_mismatch: c?.for_you === false,
                     unverified: c?.for_you === false && c?.address_verified === false,
                     resource_id: c?.resource_id, actions: c?.actions });
        setStatus('confirm');
      })
      .catch((err: unknown) => {
        const code = (err as { status?: number })?.status;
        if (code === 404 || code === 410) {
          setStatus('error');
          setMessage('This invite is no longer valid.');
          return;
        }
        setDetails(null);
        setStatus('confirm');
      });
  }, [isAuthenticated, authLoading, token, status]);

  const sendVerification = useCallback(async () => {
    if (!user?.email) return;
    try {
      await post('/auth/email/verify-request', { email: user.email });
    } catch {
      // Answered the same whether or not a link went; nothing more to say here.
    }
    setVerifySent(true);
  }, [user?.email]);

  const cancel = useCallback(() => {
    try { sessionStorage.removeItem('pending_invite_token'); } catch { /* storage unavailable */ }
    navigate('/', { replace: true });
  }, [navigate]);

  // Stash the token so the post-login flow returns here to ask.
  useEffect(() => {
    if (token && status === 'awaiting_auth') {
      sessionStorage.setItem('pending_invite_token', token);
    }
  }, [token, status]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="max-w-md w-full bg-white rounded-lg shadow-sm border p-8 text-center">
        {status === 'loading' && (
          <>
            <div className="animate-spin rounded-full h-10 w-10 border-t-2 border-b-2 border-gray-900 mx-auto mb-4" />
            <p className="text-gray-600">Loading invite...</p>
          </>
        )}

        {status === 'awaiting_auth' && (
          <>
            <h2 className="text-xl font-semibold text-gray-900 mb-2">You've been invited</h2>
            <p className="text-gray-600 mb-6">Sign in to accept this invite and start collaborating.</p>
            <p className="text-sm text-gray-500 mb-4">
              Sign in with the email address the invite was sent to.
            </p>
            <button
              onClick={() => login()}
              className="w-full bg-gray-900 text-white py-2.5 px-4 rounded-md hover:bg-gray-800 transition-colors"
            >
              Sign in to continue
            </button>
          </>
        )}

        {status === 'confirm' && (
          <>
            <h2 className="text-xl font-semibold text-gray-900 mb-2">Accept this invite?</h2>
            {details?.unverified ? (
              <div className="text-gray-600 mb-6 space-y-3">
                <p>
                  An invite is accepted only by a verified email address. Verify your email address
                  first, then open this invite link again.
                </p>
                {verifySent ? (
                  <p className="text-sm text-gray-500">If your address can be verified, a link is on its way.</p>
                ) : (
                  <button
                    onClick={() => { void sendVerification(); }}
                    className="text-gray-900 underline hover:text-gray-700 text-sm"
                  >
                    Send me a verification link
                  </button>
                )}
              </div>
            ) : details?.identity_mismatch ? (
              <p className="text-gray-600 mb-6">
                This invite is addressed to a different account than the one you are signed in with.
              </p>
            ) : (
              <>
                <p className="text-gray-600 mb-4">Accepting gives your account access to a shared resource.</p>
                {details && (details.resource_id || details.actions?.length) && (
                  <dl className="text-left text-sm text-gray-700 bg-gray-50 border rounded-md p-3 mb-6 space-y-1">
                    {details.resource_id && (
                      <div><dt className="inline font-medium">Resource: </dt><dd className="inline font-mono break-all">{details.resource_id}</dd></div>
                    )}
                    {details.actions?.length ? (
                      <div><dt className="inline font-medium">Access: </dt><dd className="inline">{details.actions.join(', ')}</dd></div>
                    ) : null}
                  </dl>
                )}
              </>
            )}
            <div className="flex gap-3">
              <button
                onClick={cancel}
                className="flex-1 border border-gray-300 text-gray-800 py-2.5 px-4 rounded-md hover:bg-gray-50 transition-colors"
              >
                Cancel
              </button>
              {!details?.identity_mismatch && (
                <button
                  onClick={() => { void doClaim(); }}
                  className="flex-1 bg-gray-900 text-white py-2.5 px-4 rounded-md hover:bg-gray-800 transition-colors"
                >
                  Accept invite
                </button>
              )}
            </div>
          </>
        )}

        {status === 'setting_up' && (
          <>
            <div className="animate-spin rounded-full h-10 w-10 border-t-2 border-b-2 border-gray-900 mx-auto mb-4" />
            <p className="text-gray-600">Invite accepted. Setting up access…</p>
          </>
        )}

        {status === 'claiming' && (
          <>
            <div className="animate-spin rounded-full h-10 w-10 border-t-2 border-b-2 border-gray-900 mx-auto mb-4" />
            <p className="text-gray-600">Accepting invite...</p>
          </>
        )}

        {status === 'success' && (
          <>
            <div className="text-green-600 mb-4">
              <svg className="h-12 w-12 mx-auto" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <h2 className="text-xl font-semibold text-gray-900 mb-2">You're in!</h2>
            <p className="text-gray-600">Redirecting to your workspace...</p>
          </>
        )}

        {status === 'error' && (
          <>
            <div className="text-red-500 mb-4">
              <svg className="h-12 w-12 mx-auto" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </div>
            <h2 className="text-xl font-semibold text-gray-900 mb-2">Unable to accept invite</h2>
            <p className="text-gray-600 mb-6">{message}</p>
            <button
              onClick={() => navigate('/login')}
              className="text-gray-900 underline hover:text-gray-700"
            >
              Go to sign in
            </button>
          </>
        )}
      </div>
    </div>
  );
}
