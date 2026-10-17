// utils/removal.ts
//
// What a removal did, said with a way back. Removing an artifact from a workspace or collection
// unlinks it; when nothing else holds it, Mantle archives it in place instead, so it stays in that
// container's Archived view. Either way the card leaves the view, so the toast names where from and
// offers Undo: a re-link for an unlink, a restore for an archive.

import { toast } from 'sonner';
import { updateArtifact } from '../api/artifacts';

/** `DELETE /artifacts/{container}/children/{id}`'s answer. */
export type RemoveResult = { id?: string; removed?: boolean; container_id?: string; archived?: boolean };

export function announceRemoval(
  result: RemoveResult | void | undefined,
  options: { from: string; relink: () => Promise<unknown>; after?: () => void },
): void {
  const undo = (fn: () => Promise<unknown>) => () => {
    void fn().then(() => options.after?.()).catch(() => toast.error('Could not undo the removal'));
  };
  if (result && result.archived && result.id) {
    const id = result.id;
    toast(`Archived`, {
      description: `It was in no other workspace or collection, so removing it from ${options.from} archived it. Turn on the Archived filter to find it.`,
      action: { label: 'Restore', onClick: undo(() => updateArtifact(id, { state: 'live' })) },
    });
    return;
  }
  toast(`Removed from ${options.from}`, {
    action: { label: 'Undo', onClick: undo(options.relink) },
  });
}
