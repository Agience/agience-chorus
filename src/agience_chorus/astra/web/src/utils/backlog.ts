import type { Artifact } from '@/context/workspace/workspace.types';
import { safeParseArtifactContext } from './artifactContext';

export const BACKLOG_ITEM = 'application/vnd.agience.backlog-item+json';

/** The Backlog-item lifecycle's last state (G6): done and out of the open Backlog. Not the
 *  artifact's own state (draft, committed, archived), which this leaves alone. */
export const CLOSED = 'closed';

/** Is this a Backlog item its loop has closed (`context.state == "closed"`)? The open Backlog hides
 *  these; the Closed chip shows them alone. */
export function isClosedBacklogItem(a: Artifact): boolean {
  const ctx = safeParseArtifactContext(a.context) as Record<string, unknown>;
  return ctx.content_type === BACKLOG_ITEM && ctx.state === CLOSED;
}
