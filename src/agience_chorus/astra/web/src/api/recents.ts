// A person's recents: their own recents collection, which Crystal finds or makes and keeps in
// the order things were opened.
import { post } from './api';

export const RECENTS_CONTENT_TYPE = 'application/vnd.agience.recents+json';

export interface RecentArtifact {
  id: string;
  name?: string;
  content_type?: string;
  context?: unknown;
}

interface RecentsResult { items?: RecentArtifact[] }

let mine: Promise<string> | null = null;

/** The caller's recents collection id, found once per page load. */
export function myRecentsId(): Promise<string> {
  if (!mine) {
    mine = post<{ id: string }>('/create', { content_type: RECENTS_CONTENT_TYPE })
      .then(r => r.id)
      .catch(err => { mine = null; throw err; });
  }
  return mine;
}

/** The recents, most recent first. */
export async function listRecents(): Promise<RecentArtifact[]> {
  const id = await myRecentsId();
  const r = await post<RecentsResult>(`/artifacts/${encodeURIComponent(id)}/op/view`, {});
  return r?.items ?? [];
}

/** Records that `artifactId` was opened; answers the recents as they now stand. */
export async function visitRecent(artifactId: string): Promise<RecentArtifact[]> {
  const id = await myRecentsId();
  const r = await post<RecentsResult>(`/artifacts/${encodeURIComponent(id)}/op/visit`, { id: artifactId });
  return r?.items ?? [];
}
