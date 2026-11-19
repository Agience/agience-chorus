import { AuthorityRefused } from '@/api/authority';
import type { GrantResponse } from '@/api/types/grant';
import { formatDay } from '@/utils/dates';

export function errorDetailOf(err: unknown, fallback: string): string {
  // Origin's session routes throw AuthorityRefused(status, detail); the store's, an axios error.
  if (err instanceof AuthorityRefused) return err.detail || fallback;
  return (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fallback;
}

/** Why an invite was not sent, in Origin's words, shown in the dialog (FR-004). An account whose
 *  address is unverified cannot sign in, so the dialog has no message of its own for that: Origin's
 *  403 for it stands, and passes through like any other refusal (BUG-071). */
export function inviteRefusal(err: unknown): string {
  return errorDetailOf(err, (err as Error)?.message || 'The invite could not be sent.');
}

/** When a pending invite was sent, as a short date (BUG-069), or '' if Origin gave none. */
export function sentOn(g: GrantResponse): string {
  const at = (g as unknown as { sent_at?: string }).sent_at;
  return formatDay(at);
}
