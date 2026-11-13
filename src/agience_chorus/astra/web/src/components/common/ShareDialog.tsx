import { useState, useCallback, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { toast } from 'sonner';
import { AuthorityRefused, describeGrantee, describeItem, describeParent, previewAtOrigin, resendInviteAtOrigin, type OriginPreview } from '@/api/authority';
import { createGrant } from '@/api/collections';
import { deleteGrant, listGrants } from '@/api/collections';
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
  // Origin's session routes throw AuthorityRefused(status, detail); the store's, an axios error.
  if (err instanceof AuthorityRefused) return err.detail || fallback;
  return (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fallback;
}

/** Why an invite was not sent, in words that say what to do (FR-004, 2026-11-13: a new account's
 *  invite was refused for its unverified address and the dialog said nothing). */
export function inviteRefusal(err: unknown): string {
  const status = err instanceof AuthorityRefused ? err.status
    : (err as { response?: { status?: number } })?.response?.status;
  const detail = errorDetailOf(err, (err as Error)?.message || 'The invite could not be sent.');
  if (status === 403 && /verif/i.test(detail)) {
    return 'Verify your email address before sending invites: the invite names you to its '
      + 'recipient by your verified address. Use the link in the sign-up email from Agience, '
      + 'then send the invite again.';
  }
  return detail;
}

// Origin's preview, in words, for a confirmation the owner answers (review 15).
function previewText(p: OriginPreview, to: string): string {
  const where = p.parents.length
    ? `inside ${p.parents.map((id) => describeParent(p, id)).join(' <- ')}` : 'as a top-level item';
  const who = p.grantees.length
    ? p.grantees.map((g) => `${describeGrantee(g)} `
        + `(${g.effect === 'deny' ? 'denied ' : ''}${g.actions.join(', ')} on ${g.resource_id})`).join('; ')
    : 'no one';
  return `Invite ${to} to ${p.resource_id}?\n\nOrigin holds it ${where}.\nAlready shared with: ${who}.`;
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
  const [sending, setSending] = useState(false);
  // Shown in the dialog itself: a toast behind an open dialog can go unseen.
  const [inviteError, setInviteError] = useState<string | null>(null);
  // What Origin said it sent, for the last invite: the item and the address. Facet never holds an
  // invite's link.
  const [sentTo, setSentTo] = useState<{ email: string; resource_id?: string;
                                         resource_name?: string } | null>(null);
  // An invite the owner has asked for and not yet confirmed (review 14, M4).
  const [pendingTo, setPendingTo] = useState<string | null>(null);
  const [routeMismatch, setRouteMismatch] = useState(false);
  // What Origin holds about the item, for the owner to confirm (review 15, L4).
  const [preview, setPreview] = useState<OriginPreview | null>(null);
  // The item is the one open in the route, never an id handed from Mantle's object (review 14).
  const { artifactId: routeId } = useParams<{ artifactId?: string }>();
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
    setSentTo(null);
    setPendingTo(null);
    setRouteMismatch(false);
    setPreview(null);
    setGrants('loading');
    return loadGrants();
  }, [open, loadGrants]);

  const handleRevoke = useCallback(async (grant: GrantResponse, what: string) => {
    setBusy(grant.id);
    try {
      await deleteGrant(grant);
      toast.success(what);
      loadGrants();
    } catch (err: unknown) {
      toast.error(errorDetailOf(err, 'Could not change access'));
    } finally {
      setBusy(null);
    }
  }, [loadGrants]);

  const handleResend = useCallback(async (grant: GrantResponse) => {
    // Origin keeps only a digest of the address it mailed, so the owner names it again.
    const to = (grant.target_entity
      || window.prompt('Send this invite again to which email address?') || '').trim();
    if (!to) return;
    setBusy(grant.id);
    try {
      // The owner confirms Origin's preview of the item again (review 15).
      const seen = await previewAtOrigin(grant.resource_id || workspaceId);
      if (!window.confirm(previewText(seen, to))) return;
      // A new invite for the same address, made and mailed by Origin, and the old one revoked
      // there (round 13). Facet never holds the link.
      await resendInviteAtOrigin(grant, to, seen.preview);
      setSentTo({ email: to });
      loadGrants();
    } catch (err: unknown) {
      toast.error(errorDetailOf(err, 'Could not resend the invite'));
    } finally {
      setBusy(null);
    }
  }, [loadGrants, workspaceId]);

  // The first step: check the route names this item, then ask the owner to confirm it by name.
  const handleInvite = useCallback(() => {
    if (!email.trim()) {
      toast.error('Please enter an email address');
      return;
    }
    if (!routeId || routeId !== workspaceId) {
      setRouteMismatch(true);
      toast.error('Open this workspace before sharing it: the page and the workspace differ');
      return;
    }
    setRouteMismatch(false);
    setPreview(null);
    setPendingTo(email.trim().toLowerCase());
    previewAtOrigin(routeId)
      .then(setPreview)
      .catch((err: unknown) => {
        setPendingTo(null);
        toast.error(errorDetailOf(err, 'Origin could not show what it holds about this'));
      });
  }, [email, routeId, workspaceId]);

  const handleConfirm = useCallback(async () => {
    const to = pendingTo;
    if (!to || !routeId || routeId !== workspaceId) {
      setRouteMismatch(true);
      return;
    }
    if (!preview || preview.resource_id !== routeId) return;
    setInviteError(null);
    setSending(true);
    try {
      // Made at Origin, in the person's Origin session, for this one address (round 13): Origin
      // makes the link and mails it there; the claimant must sign in with that address. The item
      // is the one open in the route, named as the owner confirmed it; Origin echoes both and puts
      // them in its mail (review 14). Facet never holds the link.
      const made = await createGrant(routeId, {
        grantee_type: 'invite',
        target_entity: to,
        target_entity_type: 'email',
        resource_name: workspaceName || undefined,
        preview: preview.preview,
        ...ROLE_BITS[role],
      });
      setEmail('');
      setPendingTo(null);
      setPreview(null);
      const echo = made.invite_echo;
      setSentTo({ email: echo?.email || to, resource_id: echo?.resource_id,
                  resource_name: echo?.resource_name });
      loadGrants();
    } catch (err: unknown) {
      const why = inviteRefusal(err);
      setInviteError(why);
      toast.error(why);
    } finally {
      setSending(false);
    }
  }, [pendingTo, routeId, workspaceId, workspaceName, role, loadGrants, preview]);

  // Origin lists a resource's grants only to someone who may share it, so a refused listing means
  // this person cannot invite either (2026-10-31, a tester: a Viewer got an enabled Send invite form
  // that Origin then refused).
  const mayNotShare = grants === 'hidden';

  // An invite whose claims are spent is not waiting on anyone: whoever accepted it is listed as a
  // member, by the grant the claim made.
  const spent = (g: GrantResponse) => g.grantee_type === 'invite' && g.max_claims != null
    && (g.claims_count ?? 0) >= g.max_claims;
  // An invite its target declined in the app is retired with no claim (FR-004): it stays listed
  // as declined, so its sender learns the answer instead of seeing the invite vanish.
  const declined = (g: GrantResponse) => g.grantee_type === 'invite' && g.state === 'retired'
    && (g.claims_count ?? 0) === 0;
  const members = Array.isArray(grants)
    ? grants.filter((g) => (g.state === 'active' && !spent(g)
        && (g.grantee_type === 'user' || g.grantee_type === 'invite')) || declined(g))
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
                disabled={mayNotShare}
                className="flex-1 min-w-0 px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-gray-900"
                onKeyDown={(e) => e.key === 'Enter' && handleInvite()}
              />
              <select
                value={role}
                onChange={(e) => setRole(e.target.value)}
                disabled={mayNotShare}
                className="w-32 shrink-0 px-2 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-gray-900"
              >
                {ROLES.map((r) => (
                  <option key={r.value} value={r.value}>{r.label}</option>
                ))}
              </select>
            </div>
            {inviteError && (
              <p role="alert" data-testid="share-invite-error"
                 className="rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
                {inviteError}
              </p>
            )}
            <button
              onClick={handleInvite}
              disabled={mayNotShare || sending || !email.trim()}
              className="w-full bg-gray-900 text-white py-2 px-4 rounded-md hover:bg-gray-800 transition-colors disabled:opacity-50 disabled:cursor-not-allowed text-sm"
            >
              {sending ? 'Sending...' : 'Send invite'}
            </button>
            {mayNotShare && (
              <p className="text-xs text-gray-600" data-testid="invite-not-permitted">
                You can open this workspace but not share it. Ask someone who manages it to invite people.
              </p>
            )}
            {routeMismatch && (
              <p className="text-xs text-red-600" data-testid="invite-route-mismatch">
                The open page is not this workspace. Open it, then share it.
              </p>
            )}
            {pendingTo && (
              <div className="text-xs text-gray-700 border border-gray-200 rounded p-2 space-y-2"
                data-testid="invite-confirm">
                <p>
                  Invite {pendingTo} to &ldquo;{workspaceName || 'this workspace'}&rdquo; ({routeId})?
                </p>
                {preview ? (
                  <div data-testid="invite-preview" className="space-y-1">
                    <p>Origin holds {describeItem(preview)}.</p>
                    <p>Origin holds it {preview.parents.length
                      ? <>inside {preview.parents.map((id) => describeParent(preview, id)).join(' \u2190 ')}</>
                      : <>as a top-level item</>}.</p>
                    <p>Already shared with: {preview.grantees.length
                      ? preview.grantees.map((g) => describeGrantee(g)
                          + ` (${g.effect === 'deny' ? 'denied ' : ''}${g.actions.join(', ')} on ${g.resource_id})`).join('; ')
                      : 'no one'}.</p>
                  </div>
                ) : <p className="text-gray-400">Reading what Origin holds\u2026</p>}
                <div className="flex gap-2">
                  <button onClick={() => { void handleConfirm(); }} disabled={sending || !preview}
                    className="px-2 py-1 bg-gray-900 text-white rounded disabled:opacity-50">
                    Confirm and send
                  </button>
                  <button onClick={() => setPendingTo(null)} disabled={sending}
                    className="px-2 py-1 border border-gray-300 rounded">Cancel</button>
                </div>
              </div>
            )}
            {sentTo && (
              <p className="text-xs text-gray-600" data-testid="invite-sent">
                {sentTo.resource_id
                  ? <>Origin sent an invite to &ldquo;{sentTo.resource_name || 'a shared item'}&rdquo; ({sentTo.resource_id}) to {sentTo.email}.</>
                  : <>Invite sent to {sentTo.email}.</>}
                {' '}They sign in with that address to accept it.
              </p>
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
                      ? (g.target_entity || 'An invite sent by email')
                      : you ? 'You' : (g.name || `Someone (${String(g.grantee_id).slice(0, 8)})`);
                    return (
                      <li key={g.id} className="flex items-center gap-2 px-3 py-2 text-xs">
                        <div className="flex-1 min-w-0">
                          <div className="truncate text-gray-800">{who}</div>
                          <div className="text-gray-500">{roleOf(g)}{declined(g) ? ' · invite declined'
                            : pending ? ' · invite not yet accepted' : ''}</div>
                        </div>
                        {pending && !declined(g) && g.target_entity_type === 'email' && (
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
