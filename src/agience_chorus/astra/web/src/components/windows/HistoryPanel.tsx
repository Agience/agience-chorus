import { useEffect, useState } from 'react';

import { listGrants } from '@/api/collections';
import { getAccessLog, getCommits, type AccessEvent, type ContainerCommit } from '@/api/history';
import { useAuth } from '@/hooks/useAuth';
import type { Artifact } from '@/context/workspace/workspace.types';

type Load<T> = { state: 'loading' } | { state: 'ready'; items: T[] } | { state: 'forbidden' } | { state: 'failed' };

/**
 * A card's history, as the store recorded it: what changed in what it holds
 * (`GET /artifacts/{id}/commits`, for anyone who can read it) and who reached it, what they did and
 * whether it was allowed (`GET /artifacts/{id}/access-log`). Only someone who administers the card
 * may read the access log, and that read is itself recorded; anyone else is told so rather than
 * shown an error.
 */
export function HistoryPanel({ artifact }: { artifact: Artifact }) {
  const { user } = useAuth();
  const userId = user?.id;
  const [access, setAccess] = useState<Load<AccessEvent>>({ state: 'loading' });
  const [commits, setCommits] = useState<Load<ContainerCommit>>({ state: 'loading' });
  // Who each reader is, by the name the owner gave the grant that reaches them (on this card or a
  // container it is in). Only the owner reads the access log, and only the owner lists grants, so
  // nobody learns a name here that they did not give.
  const [names, setNames] = useState<Record<string, string>>({});

  useEffect(() => {
    let cancelled = false;
    const id = String(artifact.id ?? '');
    setAccess({ state: 'loading' });
    setCommits({ state: 'loading' });
    getAccessLog(id)
      .then((page) => { if (!cancelled) setAccess({ state: 'ready', items: page.items }); })
      .catch((e: { response?: { status?: number } }) => {
        if (cancelled) return;
        const status = e?.response?.status;
        setAccess({ state: status === 403 || status === 404 ? 'forbidden' : 'failed' });
      });
    const places = [id, ...(artifact.container_ids ?? []), ...(artifact.collection_id ? [artifact.collection_id] : [])];
    Promise.allSettled([...new Set(places.filter(Boolean))].map((r) => listGrants(String(r))))
      .then((pages) => {
        if (cancelled) return;
        const found: Record<string, string> = {};
        for (const p of pages) {
          if (p.status !== 'fulfilled') continue;
          for (const g of p.value) {
            if (g.grantee_id && g.name && g.state === 'active' && !found[g.grantee_id]) found[g.grantee_id] = g.name;
          }
        }
        setNames(found);
      });
    getCommits(id)
      .then((page) => { if (!cancelled) setCommits({ state: 'ready', items: page.items ?? [] }); })
      .catch((e: { response?: { status?: number } }) => {
        if (cancelled) return;
        const status = e?.response?.status;
        setCommits({ state: status === 403 || status === 404 ? 'forbidden' : 'failed' });
      });
    return () => { cancelled = true; };
  }, [artifact.id]);  // eslint-disable-line react-hooks/exhaustive-deps

  if (access.state === 'loading' || commits.state === 'loading') {
    return <div className="p-4 text-sm text-gray-400">Loading history…</div>;
  }
  const changes = commits.state === 'ready' ? commits.items : [];
  return (
    <div className="h-full overflow-y-auto p-3 space-y-4" data-testid="history">
      {changes.length > 0 && (
        <section data-testid="history-changes">
          <h3 className="mb-1 text-xs font-semibold text-gray-500">Changes</h3>
          <table className="w-full text-xs">
            <tbody>
              {changes.map((c) => (
                <tr key={c.id} className="border-t border-gray-100">
                  <td className="py-1 pr-2 whitespace-nowrap text-gray-600">{formatTime(c.created_time ?? '')}</td>
                  <td className="py-1 pr-2 text-gray-700">{person(c.author_id ?? '', userId)}</td>
                  <td className="py-1 text-gray-700">{describeChange(c)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      {commits.state === 'failed' && (
        <div className="text-sm text-red-500">The changes could not be loaded.</div>
      )}
      <AccessSection access={access} userId={userId} names={names} />
    </div>
  );
}

function AccessSection({ access, userId, names }: {
  access: Load<AccessEvent>; userId?: string | null; names: Record<string, string>;
}) {
  if (access.state === 'forbidden') {
    return (
      <div className="text-sm text-gray-500" data-testid="history-forbidden">
        Only people who administer this card can see who accessed it.
      </div>
    );
  }
  if (access.state === 'failed') {
    return <div className="text-sm text-red-500">The history could not be loaded.</div>;
  }
  if (access.state !== 'ready' || access.items.length === 0) {
    return <div className="text-sm text-gray-500">No access recorded yet.</div>;
  }
  return (
    <section data-testid="history-panel">
      <h3 className="mb-1 text-xs font-semibold text-gray-500">Access</h3>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-gray-400">
            <th className="py-1 pr-2 font-medium">When</th>
            <th className="py-1 pr-2 font-medium">Who</th>
            <th className="py-1 pr-2 font-medium">Did</th>
            <th className="py-1 font-medium">Result</th>
          </tr>
        </thead>
        <tbody>
          {access.items.map((ev, i) => (
            <tr key={`${ev.ts}-${i}`} className="border-t border-gray-100">
              <td className="py-1 pr-2 whitespace-nowrap text-gray-600">{formatTime(ev.ts)}</td>
              <td className="py-1 pr-2 text-gray-700">{who(ev, userId, names)}</td>
              <td className="py-1 pr-2 text-gray-700">{ev.action}</td>
              <td className={`py-1 ${ev.result === 'denied' ? 'text-red-600' : 'text-green-700'}`}>
                {ev.result}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function person(id: string, userId?: string | null, names: Record<string, string> = {}): string {
  if (userId && id === userId) return 'You';
  const short = (id || '?').slice(0, 8);
  return names[id] ? `${names[id]} (${short})` : `Someone else (${short})`;
}

function who(ev: AccessEvent, userId?: string | null, names: Record<string, string> = {}): string {
  // `via` is how the caller authenticated; `actor` the persona or client acting for a person.
  const via = typeof ev.ctx?.via === 'string' ? ev.ctx.via : '';
  const actor = typeof ev.ctx?.actor === 'string' && ev.ctx.actor ? ev.ctx.actor : '';
  if (via === 'grant_key') {
    const keyId = typeof ev.ctx?.grant_key_id === 'string' ? ev.ctx.grant_key_id : ev.principal_id;
    return `Key ${String(keyId || '').slice(0, 8)}`;
  }
  const p = person(ev.principal_id, userId, names);
  return actor ? `${p}, through ${actor}` : p;
}

function describeChange(c: ContainerCommit): string {
  const parts: string[] = [];
  if (c.adds.length) parts.push(`added ${c.adds.length} card${c.adds.length === 1 ? '' : 's'}`);
  if (c.removes.length) parts.push(`removed ${c.removes.length} card${c.removes.length === 1 ? '' : 's'}`);
  const what = parts.join(', ') || 'no change to its cards';
  return c.message ? `${what} — ${c.message}` : what;
}

function formatTime(ts: string | number): string {
  const d = typeof ts === 'number' ? new Date(ts * (ts < 1e12 ? 1000 : 1)) : new Date(ts);
  return Number.isNaN(d.getTime()) ? String(ts) : d.toLocaleString();
}
