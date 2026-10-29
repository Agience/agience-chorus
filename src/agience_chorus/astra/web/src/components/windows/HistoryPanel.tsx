import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';

import { listGrants } from '@/api/collections';
import {
  getAccessLog, getVersion, listVersions, restoreVersion,
  type AccessEvent, type VersionSummary,
} from '@/api/history';
import { announceArtifactChange } from '@/constants/strings';
import { useAuth } from '@/hooks/useAuth';
import { useWorkspace } from '@/hooks/useWorkspace';
import type { Artifact } from '@/context/workspace/workspace.types';
import { errorDetail } from '@/utils/errorDetail';

type Load<T> = { state: 'loading' } | { state: 'ready'; items: T[] } | { state: 'forbidden' } | { state: 'failed' };

/**
 * A card's history, as the store recorded it, in two tabs.
 *
 * Versions: the card's earlier versions (`GET /artifacts/{id}/versions`), each readable and
 * restorable. Every content edit keeps the version it replaced; the list shows the ones this person
 * can read. 2026-10-23, a tester found History showed access only, with no way to an earlier version.
 *
 * Access: who reached it, what they did and whether it was allowed (`GET /artifacts/{id}/access-log`).
 * Only someone who administers the card may read it, and that read is itself recorded; anyone else
 * is told so rather than shown an error.
 */
export function HistoryPanel({ artifact }: { artifact: Artifact }) {
  const [tab, setTab] = useState<'versions' | 'access'>('versions');
  const { user } = useAuth();
  const userId = user?.id;
  const [access, setAccess] = useState<Load<AccessEvent>>({ state: 'loading' });
  // Who each reader is, by the name the owner gave the grant that reaches them (on this card or a
  // container it is in). Only the owner reads the access log, and only the owner lists grants, so
  // nobody learns a name here that they did not give.
  const [names, setNames] = useState<Record<string, string>>({});

  useEffect(() => {
    let cancelled = false;
    const id = String(artifact.id ?? '');
    setAccess({ state: 'loading' });
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
    return () => { cancelled = true; };
  }, [artifact.id]);  // eslint-disable-line react-hooks/exhaustive-deps

  const tabClass = (on: boolean) =>
    `px-3 py-1.5 text-xs font-medium border-b-2 ${on ? 'border-gray-800 text-gray-900' : 'border-transparent text-gray-500 hover:text-gray-700'}`;
  return (
    <div className="h-full flex flex-col" data-testid="history">
      <div role="tablist" className="flex gap-1 px-3 border-b border-gray-100">
        <button role="tab" aria-selected={tab === 'versions'} className={tabClass(tab === 'versions')}
          onClick={() => setTab('versions')}>Versions</button>
        <button role="tab" aria-selected={tab === 'access'} className={tabClass(tab === 'access')}
          onClick={() => setTab('access')}>Access</button>
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto p-3">
        {tab === 'versions'
          ? <VersionsSection artifact={artifact} userId={userId} names={names} />
          : access.state === 'loading'
            ? <div className="text-sm text-gray-400">Loading access…</div>
            : <AccessSection access={access} userId={userId} names={names} />}
      </div>
    </div>
  );
}

function VersionsSection({ artifact, userId, names }: {
  artifact: Artifact; userId?: string | null; names: Record<string, string>;
}) {
  const { isEditable, patchArtifactLocally } = useWorkspace();
  const id = String(artifact.id ?? '');
  const [versions, setVersions] = useState<Load<VersionSummary>>({ state: 'loading' });
  const [chosen, setChosen] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ title: string; content: string } | 'loading' | 'failed' | null>(null);
  const [restoring, setRestoring] = useState(false);

  const load = useCallback(() => {
    let cancelled = false;
    setVersions({ state: 'loading' });
    listVersions(id)
      .then((page) => { if (!cancelled) setVersions({ state: 'ready', items: page.items }); })
      .catch(() => { if (!cancelled) setVersions({ state: 'failed' }); });
    return () => { cancelled = true; };
  }, [id]);

  // Read again whenever the card's content changes, so a save shows here as a new version.
  useEffect(() => load(), [load, artifact.modified_time]);

  useEffect(() => {
    if (!chosen) { setPreview(null); return; }
    let cancelled = false;
    setPreview('loading');
    getVersion(id, chosen)
      .then((v) => {
        if (cancelled) return;
        const ctx = typeof v.context === 'string' ? safeJson(v.context) : (v.context ?? {});
        setPreview({ title: String((ctx as { title?: unknown }).title ?? ''), content: String(v.content ?? '') });
      })
      .catch(() => { if (!cancelled) setPreview('failed'); });
    return () => { cancelled = true; };
  }, [id, chosen]);

  const restore = async (version: VersionSummary) => {
    setRestoring(true);
    try {
      const updated = await restoreVersion(id, version.id);
      patchArtifactLocally({ ...updated, id } as Partial<Artifact>);
      announceArtifactChange({ ...(updated as unknown as Record<string, unknown>), id });
      toast(`Restored the version from ${formatTime(version.modified_time ?? '')}`, {
        description: 'It is now the current version. The one it replaced is kept in Versions.',
      });
      setChosen(null);
      load();
    } catch (err) {
      toast.error('Could not restore this version', {
        description: errorDetail(err, err instanceof Error ? err.message : 'Unknown error'),
      });
    } finally {
      setRestoring(false);
    }
  };

  if (versions.state === 'loading') return <div className="text-sm text-gray-400">Loading versions…</div>;
  if (versions.state !== 'ready') return <div className="text-sm text-red-500">The versions could not be loaded.</div>;
  if (versions.items.length <= 1) {
    return <div className="text-sm text-gray-500">No earlier versions yet. Each change to the content or title keeps the one before it.</div>;
  }
  const selected = versions.items.find((v) => v.id === chosen) ?? null;
  return (
    <section data-testid="versions-panel" className="space-y-3">
      <ul className="divide-y divide-gray-100 border border-gray-100 rounded">
        {versions.items.map((v) => (
          <li key={v.id}>
            <button
              type="button"
              onClick={() => setChosen(v.current || v.id === chosen ? null : v.id)}
              disabled={v.current}
              className={`w-full text-left px-3 py-2 text-xs ${v.id === chosen ? 'bg-gray-50' : 'hover:bg-gray-50'} disabled:cursor-default`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-gray-800 truncate">{v.title || 'Untitled'}</span>
                {v.current && <span className="shrink-0 text-[10px] uppercase tracking-wide text-green-700">Current</span>}
              </div>
              <div className="text-gray-500">
                {formatTime(v.modified_time ?? '')}{v.modified_by ? ` · ${person(v.modified_by, userId, names)}` : ''}
              </div>
            </button>
          </li>
        ))}
      </ul>
      {versions.state === 'ready' && selected && (
        <div className="border border-gray-200 rounded p-3 space-y-2" data-testid="version-preview">
          {preview === 'loading' && <div className="text-xs text-gray-400">Loading this version…</div>}
          {preview === 'failed' && <div className="text-xs text-red-500">This version could not be loaded.</div>}
          {preview && typeof preview === 'object' && (
            <>
              <div className="text-sm font-semibold text-gray-900">{preview.title || 'Untitled'}</div>
              <pre className="whitespace-pre-wrap text-xs text-gray-700 max-h-64 overflow-y-auto font-sans">{preview.content}</pre>
            </>
          )}
          {isEditable(artifact) && (
            <button
              type="button"
              disabled={restoring || preview === 'loading' || preview === 'failed'}
              onClick={() => { void restore(selected); }}
              className="px-3 py-1.5 text-xs font-medium text-white bg-gray-900 rounded hover:bg-gray-800 disabled:opacity-50"
            >
              {restoring ? 'Restoring…' : 'Restore this version'}
            </button>
          )}
        </div>
      )}
    </section>
  );
}

function safeJson(text: string): Record<string, unknown> {
  try { const v = JSON.parse(text); return v && typeof v === 'object' ? v : {}; } catch { return {}; }
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


function formatTime(ts: string | number): string {
  const d = typeof ts === 'number' ? new Date(ts * (ts < 1e12 ? 1000 : 1)) : new Date(ts);
  return Number.isNaN(d.getTime()) ? String(ts) : d.toLocaleString();
}
