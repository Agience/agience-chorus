import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';

import { actOnInvite, offeredInvites, type OfferedInvite } from '@/api/inviteArtifacts';
import { listRoles, roleNamed, type Role } from '@/api/collections';
import { openShared, waitForAccess } from './invites';
import { formatDay } from '@/utils/dates';

/**
 * Invites made for the signed-in person, shown at the top of their Inbox with Accept and Decline
 * (FR-004). Each is an invite artifact the person may read, listed by the Inbox's `invites`
 * operation, so an account whose mailbox nobody watches can accept without leaving the app.
 * Accepting and declining are taken in the person's own Origin session, at the path the invite's
 * type names. The mailed link keeps working.
 */
export function IncomingInvites() {
  const [invites, setInvites] = useState<OfferedInvite[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [roles, setRoles] = useState<Role[]>([]);

  // The roles Mantle offers name each invite's actions.
  useEffect(() => { listRoles().then(setRoles, () => setRoles([])); }, []);

  const load = useCallback(async () => {
    try {
      setInvites(await offeredInvites());
    } catch {
      // No Inbox yet, or Crystal unreachable: show nothing rather than an error strip.
      setInvites([]);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const act = useCallback(async (inv: OfferedInvite, accept: boolean) => {
    setBusy(inv.id);
    try {
      if (accept) {
        await actOnInvite(inv.id, 'accept');
        const joining = toast.loading(`Joining ${inv.resource_name || 'the shared item'}…`);
        const ready = await waitForAccess(inv.resource_id);
        toast.dismiss(joining);
        if (ready) {
          toast.success(`Accepted the invite to ${inv.resource_name || 'the shared item'}`,
                        { description: 'Opening it now.' });
          openShared(inv.resource_id);
        } else {
          // Never a false "not shared": the claim is made; the store has not caught up yet.
          toast.info('Access is on its way', {
            description: 'Your access is being set up. Open it again in a moment.',
            action: { label: 'Open', onClick: () => openShared(inv.resource_id) },
          });
        }
      } else {
        await actOnInvite(inv.id, 'decline');
        toast.success(`Declined the invite to ${inv.resource_name || 'the shared item'}`);
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
          <li key={inv.id} data-testid="incoming-invite"
              className="flex items-center justify-between gap-2 rounded px-1 py-1 text-sm">
            <span>
              You are invited to <strong>{inv.resource_name || 'a shared item'}</strong> as {roleNamed(inv.actions, roles) ?? (inv.actions.join(', ') || 'no access')}
              {inv.expires_at ? ` (until ${formatDay(inv.expires_at)})` : ''}
            </span>
            <span className="flex gap-1">
              <button type="button" disabled={busy === inv.id}
                      className="rounded bg-primary px-2 py-0.5 text-primary-foreground disabled:opacity-50"
                      onClick={() => void act(inv, true)}>Accept</button>
              <button type="button" disabled={busy === inv.id}
                      className="rounded border px-2 py-0.5 disabled:opacity-50"
                      onClick={() => void act(inv, false)}>Decline</button>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
