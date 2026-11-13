import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';

import {
  acceptInvite, declineInvite, incomingInvites, type IncomingInvite,
} from '@/api/authority';

/** The role an invite's actions amount to, in the share dialog's words (Viewer, Contributor,
 *  Editor, Collaborator, Admin). */
export function roleOf(actions: string[]): string {
  const a = new Set(actions);
  if (a.has('admin')) return 'Admin';
  if (a.has('share')) return 'Collaborator';
  if (a.has('update') || a.has('delete')) return 'Editor';
  if (a.has('create') || a.has('add')) return 'Contributor';
  if (a.has('read')) return 'Viewer';
  return actions.join(', ') || 'no access';
}

/**
 * Invites addressed to the signed-in person, shown at the top of their Inbox with Accept and
 * Decline (FR-004). They are read from Origin in the person's Origin session, so an account whose
 * mailbox nobody watches can accept without leaving the app. The mailed link keeps working.
 */
export function IncomingInvites() {
  const [invites, setInvites] = useState<IncomingInvite[]>([]);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setInvites(await incomingInvites());
    } catch {
      // No Origin session, or Origin unreachable: show nothing rather than an error strip.
      setInvites([]);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const act = useCallback(async (inv: IncomingInvite, accept: boolean) => {
    setBusy(inv.invite_id);
    try {
      if (accept) {
        await acceptInvite(inv.invite_id);
        toast.success(`Accepted ${inv.from}'s invite`, {
          description: 'It is shared with you now.',
          action: { label: 'Open', onClick: () => window.location.reload() },
        });
      } else {
        await declineInvite(inv.invite_id);
        toast.success(`Declined ${inv.from}'s invite`);
      }
    } catch (e) {
      const detail = e instanceof Error ? e.message : String(e);
      toast.error(accept ? 'The invite could not be accepted' : 'The invite could not be declined',
                  { description: detail });
    } finally {
      setBusy(null);
      await load();
    }
  }, [load]);

  if (invites.length === 0) return null;

  return (
    <section aria-label="Invitations" className="mx-3 my-2 rounded-md border bg-muted/40 p-2">
      <h2 className="px-1 pb-1 text-sm font-medium">Invitations</h2>
      <ul className="flex flex-col gap-1">
        {invites.map(inv => (
          <li key={inv.invite_id} data-testid="incoming-invite"
              className="flex items-center justify-between gap-2 rounded px-1 py-1 text-sm">
            <span>
              <strong>{inv.from || 'Someone'}</strong> invited you as {roleOf(inv.actions)}
              {inv.expires_at ? ` (until ${new Date(inv.expires_at).toLocaleDateString()})` : ''}
            </span>
            <span className="flex gap-1">
              <button type="button" disabled={busy === inv.invite_id}
                      className="rounded bg-primary px-2 py-0.5 text-primary-foreground disabled:opacity-50"
                      onClick={() => void act(inv, true)}>Accept</button>
              <button type="button" disabled={busy === inv.invite_id}
                      className="rounded border px-2 py-0.5 disabled:opacity-50"
                      onClick={() => void act(inv, false)}>Decline</button>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
