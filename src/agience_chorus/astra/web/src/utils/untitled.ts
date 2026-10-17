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

/** A new card still as it was created: no content, and the title it was given. */
export function isUntouchedNewCard(artifact: Pick<Artifact, 'content' | 'context'>, defaultTitle: string): boolean {
  const content = typeof artifact.content === 'string' ? artifact.content : JSON.stringify(artifact.content ?? '');
  return (content === '' || content === '""') && artifactTitle(artifact) === defaultTitle;
}

// New cards created in this tab and not yet closed: artifact id -> the default title it was given.
// A create path records its card here; closing the card's window takes it back out and, when the
// card is still untouched, discards it. Kept beside the rule rather than threaded through every
// open callback, which pass an artifact and nothing else.
const newCards = new Map<string, string>();

export function markNewCard(id: string, defaultTitle: string): void {
  newCards.set(String(id), defaultTitle);
}

/** The default title `id` was created with, if it is a new card; it is no longer one after this. */
export function takeNewCard(id: string): string | undefined {
  const title = newCards.get(String(id));
  newCards.delete(String(id));
  return title;
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
