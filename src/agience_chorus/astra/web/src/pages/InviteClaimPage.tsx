import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { claimInvite } from '../api/artifacts';
import { get } from '../api/api';
import { toast } from 'sonner';

/** `GET /grants/invite-details`: what an invite grants, read without claiming it. */
type InviteDetails = {
  valid?: boolean;
  identity_mismatch?: boolean;
  resource_id?: string;
  granted_by?: string;
  name?: string;
};

/**
 * /invite/:token -- public invite claim page.
 *
 * PII rules:
 * - Pre-auth: show only "You've been invited to collaborate." No inviter
 *   name, no resource name, no email hint.
 * - Post-auth: show what `/grants/invite-details` returns without claiming
 *   (the invite's name, the resource id, the granting user's id; or that the
 *   invite is addressed to someone else) and claim only on an explicit
 *   Accept click. Opening the link never claims anything by itself, so a
 *   crafted link cannot attach a grant to a signed-in account unasked.
 */
export default function InviteClaimPage() {
  const { token } = useParams<{ token: string }>();
  const navigate = useNavigate();
  const { isAuthenticated, loading: authLoading, login } = useAuth();

  const [status, setStatus] = useState<'loading' | 'awaiting_auth' | 'confirm' | 'claiming' | 'success' | 'error'>('loading');
  const [message, setMessage] = useState('');
  const [inviteContext, setInviteContext] = useState<{
    valid?: boolean;
    has_target?: boolean;
    target_type?: string;
  } | null>(null);
  const [details, setDetails] = useState<InviteDetails | null>(null);

  const claimedRef = useRef(false);
  const detailsRequestedRef = useRef(false);

  // Pre-auth: fetch non-PII invite context.
  useEffect(() => {
    if (!token) {
      setStatus('error');
      setMessage('Invalid invite link.');
      return;
    }

    get<{ valid?: boolean; has_target?: boolean; target_type?: string }>(
      `/grants/invite-context?token=${encodeURIComponent(token)}`,
    )
      .then((ctx) => {
        setInviteContext(ctx);
        if (!ctx?.valid) {
          setStatus('error');
          setMessage('This invite is no longer valid.');
        } else if (!isAuthenticated && !authLoading) {
          setStatus('awaiting_auth');
        }
      })
      .catch((err: unknown) => {
        // 404/410 from the context endpoint = invalid invite.
        const code = (err as { response?: { status?: number } })?.response?.status;
        if (code === 404 || code === 410) {
          setStatus('error');
          setMessage('This invite is no longer valid.');
        } else if (!isAuthenticated && !authLoading) {
          setStatus('awaiting_auth');
        }
      });
  }, [token]); // eslint-disable-line react-hooks/exhaustive-deps

  // Claim, only from the Accept button.
  const doClaim = useCallback(async () => {
    if (!token || claimedRef.current) return;
    claimedRef.current = true;
    setStatus('claiming');

    try {
      const result = await claimInvite(token);
      sessionStorage.removeItem('pending_invite_token');
      setStatus('success');
      toast.success('Invite accepted!');

      const resourceId = result?.resource_id;
      setTimeout(
        () => navigate(resourceId ? `/${resourceId}` : '/', { replace: true }),
        1200,
      );
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
    get<InviteDetails>(`/grants/invite-details?token=${encodeURIComponent(token)}`)
      .then((d) => {
        setDetails(d ?? null);
        setStatus('confirm');
      })
      .catch((err: unknown) => {
        const code = (err as { response?: { status?: number } })?.response?.status;
        if (code === 404 || code === 410) {
          setStatus('error');
          setMessage('This invite is no longer valid.');
          return;
        }
        setDetails(null);
        setStatus('confirm');
      });
  }, [isAuthenticated, authLoading, token, status]);

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
            {inviteContext?.has_target && inviteContext.target_type === 'email' && (
              <p className="text-sm text-gray-500 mb-4">
                This invite is for a specific email address.
              </p>
            )}
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
            {details?.identity_mismatch ? (
              <p className="text-gray-600 mb-6">
                This invite is addressed to a different account than the one you are signed in with.
              </p>
            ) : (
              <>
                <p className="text-gray-600 mb-4">Accepting gives your account access to a shared resource.</p>
                {details && (details.name || details.resource_id || details.granted_by) && (
                  <dl className="text-left text-sm text-gray-700 bg-gray-50 border rounded-md p-3 mb-6 space-y-1">
                    {details.name && (
                      <div><dt className="inline font-medium">Invite: </dt><dd className="inline">{details.name}</dd></div>
                    )}
                    {details.resource_id && (
                      <div><dt className="inline font-medium">Resource: </dt><dd className="inline font-mono break-all">{details.resource_id}</dd></div>
                    )}
                    {details.granted_by && (
                      <div><dt className="inline font-medium">Shared by: </dt><dd className="inline font-mono break-all">{details.granted_by}</dd></div>
                    )}
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
