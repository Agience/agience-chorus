import { useState, useCallback, useEffect } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { toast } from 'sonner';
import { actionsOf, describeGrantee, describeItem, describeParent, previewAtOrigin, resendInviteAtOrigin, type OriginPreview } from '@/api/authority';
import { getArtifact } from '@/api/artifacts';
import { createGrant, listRoles, roleNamed, shownRole, type Role } from '@/api/collections';
import { safeParseArtifactContext } from '@/utils/artifactContext';
import { deleteGrant, listGrants, markMembers, type Member } from '@/api/collections';
import type { GrantResponse } from '@/api/types/grant';
import { errorDetailOf, inviteRefusal, sentOn } from './shareText';
import { useAuth } from '@/hooks/useAuth';

interface ShareDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The artifact shared: any artifact, opened from first-party UI only (FR-030). */
  resourceId?: string;
  /** The workspace header's name for the same id. Kept for that caller; the dialog shows only the
   *  title it loads itself. */
  workspaceId?: string;
  workspaceName?: string;
}

/** The shared item as the store holds it, loaded by the dialog itself, never a caller's name. */
interface SharedItem { title: string; contentType: string; isContainer: boolean }

// The role whose actions a grant holds exactly, else "Custom".
function roleOf(grant: GrantResponse, roles: Role[]): string {
  return roleNamed(actionsOf(grant as unknown as Record<string, unknown>), roles) ?? 'Custom';
}

function copy(text: string) {
  navigator.clipboard.writeText(text).then(
    () => toast.success('Link copied to clipboard'),
    () => toast.error('Failed to copy link'),
  );
}

export function ShareDialog({ open, onOpenChange, resourceId, workspaceId: legacyId }: ShareDialogProps) {
  // FR-030: any artifact is shared by its own id. What the person confirms is bound to Origin's
  // preview digest of exactly this id (review 14's intent, "what you confirm is what you share"),
  // which replaces the old check that the page's route named it.
  const workspaceId = resourceId || legacyId || '';
  const [item, setItem] = useState<SharedItem | 'loading' | 'missing'>('loading');
  const [parentNames, setParentNames] = useState<Record<string, string>>({});
  const workspaceName = typeof item === 'object' ? item.title : undefined;
  const [email, setEmail] = useState('');
  // The roles offered are Mantle's; the first is chosen until the person picks another.
  const [roles, setRoles] = useState<Role[]>([]);
  const [role, setRole] = useState('');
  const [sending, setSending] = useState(false);
  // Shown in the dialog itself: a toast behind an open dialog can go unseen.
  const [inviteError, setInviteError] = useState<string | null>(null);
  // What Origin said it sent, for the last invite: the item and the address. Facet never holds an
  // invite's link.
  const [sentTo, setSentTo] = useState<{ email: string; resource_id?: string;
                                         resource_name?: string } | null>(null);
  // An invite the owner has asked for and not yet confirmed (review 14, M4).
  const [pendingTo, setPendingTo] = useState<string | null>(null);
  // When the pending confirmation is a Resend: the invite it replaces. Resend is confirmed in the
  // same inline step as Send, never a native dialog, which can go unseen behind this one.
  const [resendOf, setResendOf] = useState<GrantResponse | null>(null);
  const [routeMismatch, setRouteMismatch] = useState(false);
  // What Origin holds about the item, for the owner to confirm (review 15, L4).
  const [preview, setPreview] = useState<OriginPreview | null>(null);
  const routeId = workspaceId;
  const [grants, setGrants] = useState<Member[] | 'loading' | 'hidden' | 'unread'>('loading');
  const [busy, setBusy] = useState<string | null>(null);
  const { user } = useAuth();

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    listRoles()
      .then((got) => {
        if (cancelled) return;
        setRoles(got);
        setRole((r) => r || (got[0]?.name ?? ''));
      })
      .catch(() => { if (!cancelled) setRoles([]); });
    return () => { cancelled = true; };
  }, [open]);

  const deepLink = `${window.location.origin}/${workspaceId}`;

  const handleCopyLink = useCallback(() => copy(deepLink), [deepLink]);

  // Who has access is shown to whoever may manage it; anyone else is not offered the list.
  const loadGrants = useCallback(() => {
    let cancelled = false;
    listGrants(workspaceId)
      .then((items) => markMembers(workspaceId, items).then(
        (marked) => { if (!cancelled) setGrants(marked); },
        () => { if (!cancelled) setGrants('unread'); }),
      () => { if (!cancelled) setGrants('hidden'); });
    return () => { cancelled = true; };
  }, [workspaceId]);

  // The dialog names the item from the store, by its id, when it opens (FR-030). A caller cannot put a
  // name in front of a different id; an id the store does not give this person is refused.
  useEffect(() => {
    if (!open || !workspaceId) return;
    let cancelled = false;
    setItem('loading');
    getArtifact(workspaceId)
      .then((a) => {
        if (cancelled) return;
        if (!a || String(a.id) !== String(workspaceId)
            && String((a as { root_id?: string }).root_id ?? '') !== String(workspaceId)) {
          setItem('missing');
          return;
        }
        const ctx = safeParseArtifactContext(a.context) as Record<string, unknown>;
        const contentType = String(ctx.content_type || (a as { content_type?: string }).content_type || '');
        setItem({ title: String(ctx.title || (a as { name?: string }).name || 'Untitled'), contentType,
                  isContainer: /collection|workspace/.test(contentType)
                    || Boolean((a as { has_children?: boolean }).has_children) });
      })
      .catch(() => { if (!cancelled) setItem('missing'); });
    return () => { cancelled = true; };
  }, [open, workspaceId]);

  // Who it inherits access from (FR-030): the parents Origin's preview names, by the title the store
  // gives each. Read-only for now; BUG-074 adds "blocked from" and the Admin switch here.
  useEffect(() => {
    if (!open || typeof item !== 'object') return;
    let cancelled = false;
    previewAtOrigin(workspaceId)
      .then(async (p) => {
        const names: Record<string, string> = {};
        for (const pid of p.parents ?? []) {
          try {
            const a = await getArtifact(pid);
            const ctx = safeParseArtifactContext(a.context) as Record<string, unknown>;
            names[pid] = String(ctx.title || (a as { name?: string }).name || pid);
          } catch { names[pid] = describeParent(p, pid); }
        }
        if (!cancelled) setParentNames(names);
      })
      .catch(() => { if (!cancelled) setParentNames({}); });
    return () => { cancelled = true; };
  }, [open, item, workspaceId]);

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
    // The owner confirms Origin's preview of the item again (review 15), inline, as for Send.
    setInviteError(null);
    setPreview(null);
    setResendOf(grant);
    setPendingTo(to);
    previewAtOrigin(grant.resource_id || workspaceId)
      .then(setPreview)
      .catch((err: unknown) => {
        setPendingTo(null);
        setResendOf(null);
        toast.error(errorDetailOf(err, 'Origin could not show what it holds about this'));
      });
  }, [workspaceId]);

  const cancelPending = useCallback(() => {
    setPendingTo(null);
    setResendOf(null);
    setPreview(null);
  }, []);

  // The first step: check the route names this item, then ask the owner to confirm it by name.
  const handleInvite = useCallback(() => {
    if (!email.trim()) {
      toast.error('Please enter an email address');
      return;
    }
    if (item === 'missing') {
      setRouteMismatch(true);
      toast.error("Couldn't load this artifact, so it can't be shared");
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
  }, [email, routeId, item]);

  const handleConfirm = useCallback(async () => {
    const to = pendingTo;
    if (resendOf && to) {
      // A Resend: a new invite for the same address, made and mailed by Origin, and the old one
      // revoked there (round 13). Facet never holds the link.
      const target = resendOf.resource_id || routeId;
      if (!preview || preview.resource_id !== target) return;
      setInviteError(null);
      setSending(true);
      setBusy(resendOf.id);
      try {
        await resendInviteAtOrigin(resendOf, to, preview.preview);
        setPendingTo(null);
        setResendOf(null);
        setPreview(null);
        setSentTo({ email: to });
        loadGrants();
      } catch (err: unknown) {
        const why = errorDetailOf(err, 'Could not resend the invite');
        setInviteError(why);
        toast.error(why);
      } finally {
        setSending(false);
        setBusy(null);
      }
      return;
    }
    if (!to || !routeId || typeof item !== 'object') {
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
        actions: roles.find((r) => r.name === role)?.actions ?? [],
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
  }, [pendingTo, resendOf, routeId, item, workspaceName, role, roles, loadGrants, preview]);

  // Origin lists a resource's grants only to someone who may share it, so a refused listing means
  // this person cannot invite either (2026-10-31, a tester: a Viewer got an enabled Send invite form
  // that Origin then refused).
  const mayNotShare = grants === 'hidden';

  // Who is listed, and how, is the resource's types' answer (the `members` op): a member, an
  // invite still waiting, or an invite its target declined.
  const members = Array.isArray(grants) ? grants : [];
  const declined = (g: Member) => g.mark === 'declined';

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Share {workspaceName || (item === 'missing' ? 'this artifact' : '…')}</DialogTitle>
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
                disabled={mayNotShare || !roles.length}
                className="w-32 shrink-0 px-2 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-gray-900"
              >
                {roles.map((r) => (
                  <option key={r.name} value={r.name} title={r.actions.join(', ')}>{shownRole(r.name)}</option>
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
              disabled={mayNotShare || sending || !email.trim() || !role}
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
                Couldn&rsquo;t load this artifact, so it can&rsquo;t be shared.
              </p>
            )}
            {pendingTo && (
              <div className="text-xs text-gray-700 border border-gray-200 rounded p-2 space-y-2"
                data-testid="invite-confirm">
                <p>
                  {resendOf ? 'Send the invite again to ' : 'Invite '}{pendingTo} to
                  {' '}&ldquo;{workspaceName || 'this workspace'}&rdquo; ({resendOf?.resource_id || routeId})?
                </p>
                {preview ? (
                  <div data-testid="invite-preview" className="space-y-1">
                    <p>Origin holds {describeItem(preview)}.</p>
                    {typeof item === 'object' && item.isContainer && (
                      <p data-testid="invite-scope">The access reaches everything inside it, which inherits it.</p>
                    )}
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
                  <button onClick={() => { void handleConfirm(); }} disabled={sending || !preview || typeof item !== 'object'}
                    className="px-2 py-1 bg-gray-900 text-white rounded disabled:opacity-50">
                    {resendOf ? 'Confirm and resend' : 'Confirm and send'}
                  </button>
                  <button onClick={cancelPending} disabled={sending}
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
              {Object.keys(parentNames).length > 0 && (
                <p className="text-xs text-gray-500" data-testid="share-inherits">
                  Inherits from {Object.values(parentNames).join(', ')}
                </p>
              )}
              {grants === 'loading' ? (
                <p className="text-xs text-gray-400">Loading…</p>
              ) : grants === 'unread' ? (
                <p className="text-xs text-gray-500">Who has access could not be read. Close and open again to retry.</p>
              ) : members.length === 0 ? (
                <p className="text-xs text-gray-500">No one has been invited yet.</p>
              ) : (
                <ul className="divide-y divide-gray-100 border border-gray-100 rounded max-h-48 overflow-y-auto">
                  {members.map((g) => {
                    const pending = g.mark !== 'member';
                    const you = !pending && g.grantee_id === user?.id;
                    const who = pending
                      ? (g.target_entity || 'An invite sent by email')
                      : you ? 'You' : (g.name || `Someone (${String(g.grantee_id).slice(0, 8)})`);
                    return (
                      <li key={g.id} className="flex items-center gap-2 px-3 py-2 text-xs">
                        <div className="flex-1 min-w-0">
                          <div className="truncate text-gray-800">{who}</div>
                          <div className="text-gray-500">{roleOf(g, roles)}{declined(g) ? ' · invite declined'
                            : pending ? ' · invite not yet accepted' : ''}{pending && sentOn(g)
                              ? ` · sent ${sentOn(g)}` : ''}</div>
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
