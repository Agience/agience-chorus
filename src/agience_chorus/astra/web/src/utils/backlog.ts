import type { Artifact } from '@/context/workspace/workspace.types';
import { safeParseArtifactContext } from './artifactContext';

export const BACKLOG_ITEM = 'application/vnd.agience.backlog-item+json';

/** The Backlog-item lifecycle's last state (G6): done and out of the open Backlog. Not the
 *  artifact's own state (draft, committed, archived), which this leaves alone. */
export const CLOSED = 'closed';

/** A Markdown Backlog report's status: the rest of its first line starting "Status:", trimmed, or
 *  null when it has none. The one rule is lumen/ui/application/vnd.agience.backlog-item+json/
 *  status-line.json, whose cases every reader is tested against. */
export function statusLine(text: string): string | null {
  const m = /^Status:(.*)$/m.exec(text ?? '');
  return m ? m[1].trim() : null;
}

/** Is a status closed? It starts with the word "closed" (so "closedown" is not). */
export function isClosedStatus(status: string | null): boolean {
  return status !== null && /^closed\b/i.test(status);
}

/** Is this a Backlog item its loop has closed? A typed item by `context.state == "closed"`; an older
 *  Markdown report by its Status line (G6). The open Backlog hides these; the Closed chip shows
 *  them alone. */
export function isClosedBacklogItem(a: Artifact): boolean {
  const ctx = safeParseArtifactContext(a.context) as Record<string, unknown>;
  if (ctx.content_type === BACKLOG_ITEM) return ctx.state === CLOSED;
  if (ctx.content_type === 'text/markdown') {
    return isClosedStatus(statusLine(String((a as { content?: unknown }).content ?? '')));
  }
  return false;
}
