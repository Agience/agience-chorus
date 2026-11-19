// Saved views: view-type artifacts Crystal makes and runs. A view links the container it views
// and keeps the choices it was saved with.
import { post } from './api';
import type { ArtifactResponse } from './types';
import type { ViewChoices, ViewResult } from './collections';

export const VIEW_CONTENT_TYPE = 'application/vnd.agience.view+json';

/** Saves a view of `targetId` with `choices`, in `containerId` when one is given. */
export function saveView(targetId: string, choices: ViewChoices, containerId?: string): Promise<ArtifactResponse> {
  return post<ArtifactResponse>('/create', {
    content_type: VIEW_CONTENT_TYPE,
    target_id: targetId,
    choices,
    ...(containerId ? { container_id: containerId } : {}),
  });
}

/** A saved view as Crystal runs it: its container's view under its choices, and that container. */
export function runSavedView(viewId: string): Promise<ViewResult & { target_id: string }> {
  return post<ViewResult & { target_id: string }>(`/artifacts/${encodeURIComponent(viewId)}/op/view`, {});
}
