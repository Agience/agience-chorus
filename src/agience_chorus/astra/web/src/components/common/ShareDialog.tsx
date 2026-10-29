import { useState, useCallback, useEffect } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { toast } from 'sonner';
import { post } from '@/api/api';
import { deleteGrant, listGrants, resendInvite } from '@/api/collections';
import type { GrantResponse } from '@/api/types/grant';
import { useAuth } from '@/hooks/useAuth';

interface ShareDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workspaceId: string;
  workspaceName?: string;
}

const ROLES = [
  { value: 'viewer', label: 'Viewer' },
  { value: 'contributor', label: 'Contributor (adds, changes nothing of others)' },
  { value: 'editor', label: 'Editor' },
  { value: 'collaborator', label: 'Collaborator' },
  { value: 'admin', label: 'Admin' },
];

// Role -> CRUDEASIO bit bundle. Must match backend Grant.ROLE_PRESETS.
const ROLE_BITS: Record<string, Record<string, boolean>> = {
  viewer: { can_read: true },
  contributor: { can_create: true, can_read: true },
  editor: { can_create: true, can_read: true, can_update: true, can_delete: true },
  collaborator: {
    can_create: true,
    can_read: true,
    can_update: true,
    can_delete: true,
    can_evict: true,
    can_invoke: true,
    can_add: true,
    can_share: true,
  },
  admin: {
    can_create: true,
    can_read: true,
    can_update: true,
    can_delete: true,
    can_evict: true,
    can_invoke: true,
    can_add: true,
    can_share: true,
    can_admin: true,
  },
};

const FLAGS = ['can_create', 'can_read', 'can_update', 'can_delete', 'can_evict', 'can_invoke',
  'can_add', 'can_share', 'can_admin'] as const;

// The role a grant's bits are exactly, else "Custom".
function roleOf(grant: GrantResponse): string {
  const held = (f: string) => Boolean((grant as unknown as Record<string, unknown>)[f]);
  const match = ROLES.find((r) => FLAGS.every((f) => held(f) === Boolean(ROLE_BITS[r.value][f])));
  return match ? match.label.split(' (')[0] : 'Custom';
}

function errorDetailOf(err: unknown, fallback: string): string {
  return (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fallback;
}

function copy(text: string) {
  navigator.clipboard.writeText(text).then(
    () => toast.success('Link copied to clipboard'),
    () => toast.error('Failed to copy link'),
  );
}

export function ShareDialog({ open, onOpenChange, workspaceId, workspaceName }: ShareDialogProps) {
  const [email, setEmail] = useState('');
  const [role, setRole] = useState('viewer');
  const [message, setMessage] = useState('');
  const [sending, setSending] = useState(false);
  // An invite whose mail did not go: its link, for the owner to pass on.
  const [unsent, setUnsent] = useState<{ to: string; url: string } | null>(null);
  const [grants, setGrants] = useState<GrantResponse[] | 'loading' | 'hidden'>('loading');
  const [busy, setBusy] = useState<string | null>(null);
  const { user } = useAuth();

  const deepLink = `${window.location.origin}/${workspaceId}`;

  const handleCopyLink = useCallback(() => copy(deepLink), [deepLink]);

  // Who has access is shown to whoever may manage it; anyone else is not offered the list.
  const loadGrants = useCallback(() => {
    let cancelled = false;
    listGrants(workspaceId)
      .then((items) => { if (!cancelled) setGrants(items); })
      .catch(() => { if (!cancelled) setGrants('hidden'); });
    return () => { cancelled = true; };
  }, [workspaceId]);

  useEffect(() => {
    if (!open) return;
    setUnsent(null);
    setGrants('loading');
    return loadGrants();
  }, [open, loadGrants]);

  const handleRevoke = useCallback(async (grant: GrantResponse, what: string) => {
    setBusy(grant.id);
    try {
      await deleteGrant(grant.id);
      toast.success(what);
      loadGrants();
    } catch (err: unknown) {
      toast.error(errorDetailOf(err, 'Could not change access'));
    } finally {
      setBusy(null);
    }
  }, [loadGrants]);

  const handleResend = useCallback(async (grant: GrantResponse) => {
    const to = grant.target_entity || 'the invitee';
    setBusy(grant.id);
    try {
      const again = await resendInvite(grant.id);
      if (again.email_sent) {
        setUnsent(null);
        toast.success(`Invite sent again to ${to}`, { description: 'The link sent before no longer works.' });
      } else if (again.claim_url) {
        setUnsent({ to, url: again.claim_url });
      }
      loadGrants();
    } catch (err: unknown) {
      toast.error(errorDetailOf(err, 'Could not resend the invite'));
    } finally {
      setBusy(null);
    }
  }, [loadGrants]);

  const handleInvite = useCallback(async () => {
    if (!email.trim()) {
      toast.error('Please enter an email address');
      return;
    }
    setSending(true);
    const to = email.trim().toLowerCase();
    try {
      const made = await post<GrantResponse>('/grants', {
        resource_id: workspaceId,
        grantee_type: 'invite',
        target_entity: to,
        target_entity_type: 'email',
        max_claims: 1,
        // Named role is the source of truth; the backend derives CRUDEASIO
        // bits from Grant.ROLE_PRESETS.
        role,
        message: message.trim() || null,
        // CRUDEASIO bits are included for legacy servers that don't
        // support the `role` parameter.
        ...ROLE_BITS[role],
      });
      setEmail('');
      setMessage('');
      // Said as it happened: "sent" only when the mail went, else the link to pass on.
      if (made.email_sent) {
        setUnsent(null);
        toast.success(`Invite sent to ${to}`);
      } else if (made.claim_url) {
        setUnsent({ to, url: made.claim_url });
      }
      loadGrants();
    } catch (err: unknown) {
      toast.error(errorDetailOf(err, 'Failed to create invite'));
    } finally {
      setSending(false);
    }
  }, [email, role, workspaceId, message, loadGrants]);

  const members = Array.isArray(grants)
    ? grants.filter((g) => g.state === 'active' && (g.grantee_type === 'user' || g.grantee_type === 'invite'))
    : [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Share {workspaceName || 'workspace'}</DialogTitle>
          <DialogDescription>Invite someone by email or copy a link.</DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="space-y-3">
            <label className="text-sm font-medium text-gray-700">Invite by email</label>
            <div className="flex gap-2">
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@example.com"
                className="flex-1 min-w-0 px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-gray-900"
                onKeyDown={(e) => e.key === 'Enter' && handleInvite()}
              />
              <select
                value={role}
                onChange={(e) => setRole(e.target.value)}
                className="w-32 shrink-0 px-2 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-gray-900"
              >
                {ROLES.map((r) => (
                  <option key={r.value} value={r.value}>{r.label}</option>
                ))}
              </select>
            </div>
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="Add a message (optional)"
              rows={2}
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-gray-900 resize-none"
            />
            <button
              onClick={handleInvite}
              disabled={sending || !email.trim()}
              className="w-full bg-gray-900 text-white py-2 px-4 rounded-md hover:bg-gray-800 transition-colors disabled:opacity-50 disabled:cursor-not-allowed text-sm"
            >
              {sending ? 'Sending...' : 'Send invite'}
            </button>
            {unsent && (
              <div className="rounded-md border border-amber-200 bg-amber-50 p-3 space-y-2" data-testid="invite-unsent">
                <p className="text-xs text-amber-900">
                  The invite for {unsent.to} is ready, but it could not be emailed. Send them this link yourself:
                </p>
                <div className="flex gap-2">
                  <input type="text" readOnly value={unsent.url} aria-label="Invite link"
                    className="flex-1 min-w-0 px-2 py-1 text-xs bg-white border border-amber-200 rounded text-gray-700" />
                  <button onClick={() => copy(unsent.url)}
                    className="px-3 py-1 text-xs border border-amber-300 rounded hover:bg-amber-100">Copy</button>
                </div>
              </div>
            )}
          </div>

          {grants !== 'hidden' && (
            <div className="space-y-2" data-testid="share-members">
              <label className="text-sm font-medium text-gray-700">People with access</label>
              {grants === 'loading' ? (
                <p className="text-xs text-gray-400">Loading…</p>
              ) : members.length === 0 ? (
                <p className="text-xs text-gray-500">No one has been invited yet.</p>
              ) : (
                <ul className="divide-y divide-gray-100 border border-gray-100 rounded max-h-48 overflow-y-auto">
                  {members.map((g) => {
                    const pending = g.grantee_type === 'invite';
                    const you = !pending && g.grantee_id === user?.id;
                    const who = pending
                      ? (g.target_entity || g.name || 'Anyone with the link')
                      : you ? 'You' : (g.name || `Someone (${String(g.grantee_id).slice(0, 8)})`);
                    return (
                      <li key={g.id} className="flex items-center gap-2 px-3 py-2 text-xs">
                        <div className="flex-1 min-w-0">
                          <div className="truncate text-gray-800">{who}</div>
                          <div className="text-gray-500">{roleOf(g)}{pending ? ' · invite not yet accepted' : ''}</div>
                        </div>
                        {pending && g.target_entity_type === 'email' && (
                          <button disabled={busy === g.id} onClick={() => { void handleResend(g); }}
                            className="px-2 py-1 border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50">Resend</button>
                        )}
                        {!you && (
                          <button disabled={busy === g.id}
                            onClick={() => { void handleRevoke(g, pending ? `Invite to ${who} revoked` : `${who} no longer has access`); }}
                            className="px-2 py-1 border border-gray-300 rounded text-red-600 hover:bg-red-50 disabled:opacity-50">
                            {pending ? 'Revoke' : 'Remove'}
                          </button>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          )}

          <div className="relative">
            <div className="absolute inset-0 flex items-center">
              <span className="w-full border-t border-gray-200" />
            </div>
            <div className="relative flex justify-center text-xs uppercase">
              <span className="bg-white px-2 text-gray-500">or</span>
            </div>
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium text-gray-700">Copy link</label>
            <p className="text-xs text-gray-500">Anyone with the link can navigate here, but only invited users can access content.</p>
            <div className="flex gap-2">
              <input
                type="text"
                value={deepLink}
                readOnly
                className="flex-1 min-w-0 px-3 py-2 text-sm bg-gray-50 border border-gray-200 rounded-md text-gray-600"
              />
              <button
                onClick={handleCopyLink}
                className="px-4 py-2 text-sm border border-gray-300 rounded-md hover:bg-gray-50 transition-colors"
              >
                Copy
              </button>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
