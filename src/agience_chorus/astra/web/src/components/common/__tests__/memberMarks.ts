// A stand-in for Crystal's `members` op in dialog tests: it marks grants as the root type's
// `members` block declares (Crystal's own tests hold the rule; these hold the dialog's display).
type G = { grantee_type?: string; state?: string; claims_count?: number | null; max_claims?: number | null };

function markOf(g: G): string | null {
  if (g.grantee_type === 'invite' && g.state === 'retired' && !g.claims_count) return 'declined';
  if (g.grantee_type === 'invite' && g.state === 'active'
      && !(g.max_claims != null && (g.claims_count ?? 0) >= g.max_claims)) return 'invited';
  if (g.grantee_type === 'user' && g.state === 'active') return 'member';
  return null;
}

export function marked<T extends G>(grants: T[]): (T & { mark: string })[] {
  return grants.flatMap((g) => { const mark = markOf(g); return mark ? [{ ...g, mark }] : []; });
}
