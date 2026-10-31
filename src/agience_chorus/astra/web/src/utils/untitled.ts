// utils/untitled.ts
//
// New cards' default titles, and telling a new card nobody touched from one that is in use.
// 2026-10-13, a tester: four cards titled "Untitled Search" could not be told apart, and a new card
// opened and closed without a change stayed behind.

import type { Artifact } from '@/context/workspace/workspace.types';
import { safeParseArtifactContext } from './artifactContext';

/** The card's title as cards show it. */
export function artifactTitle(artifact: Pick<Artifact, 'context'>): string {
  const ctx = safeParseArtifactContext(artifact.context);
  return String(ctx.title || ctx.filename || '').trim();
}

/** A workspace or collection with `name` set to the title it is shown by: its context's title,
 * else the `name` an older row carries. 2026-10-23, a tester: one made as a card in another
 * workspace has a title and no `name`, and the collection picker, the command palette and the tabs,
 * which read `name`, showed it blank. */
export function titled<T extends { name?: string; context?: unknown }>(container: T): T {
  const title = artifactTitle({ context: container.context } as Pick<Artifact, 'context'>);
  return { ...container, name: title || String(container.name ?? '').trim() };
}

/** `base` if no title in `existing` takes it, else `base 2`, `base 3`, …: the first free number. */
export function nextUntitledTitle(base: string, existing: Iterable<string>): string {
  const taken = new Set<number>();
  const pattern = new RegExp(`^${base.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?: (\\d+))?$`);
  for (const title of existing) {
    const m = pattern.exec(title.trim());
    if (m) taken.add(m[1] ? Number(m[1]) : 1);
  }
  let n = 1;
  while (taken.has(n)) n += 1;
  return n === 1 ? base : `${base} ${n}`;
}

/** The title to store when one is saved: what was typed, or, when that is blank, the first line of
 * the content, else the title it had. A card always keeps a name it can be told apart by. */
export function titleOrFallback(typed: string, content: unknown, previous: string): string {
  const title = typed.trim();
  if (title) return title;
  const text = typeof content === 'string' ? content : '';
  const firstLine = text.split(/\r?\n/).map((l) => l.replace(/^#+\s*/, '').trim()).find(Boolean) ?? '';
  return firstLine.slice(0, 80) || previous.trim() || 'Untitled';
}
