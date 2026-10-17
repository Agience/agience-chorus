// components/modals/TrashDialog.tsx
//
// The person's Trash: what they deleted in the last 30 days, each with Restore and Delete
// permanently. Mantle deletes an item for good once its `purge_after` passes.

import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { deleteArtifact, listTrash, updateArtifact } from '@/api/artifacts';
import type { ArtifactResponse } from '@/api/types/artifact';
import { BUTTON_LABELS, CARD_CONFIRM, TRASH_RETENTION_DAYS } from '@/constants/strings';
import { useConfirm } from '@/context/dialog/useConfirm';
import { useWorkspace } from '@/hooks/useWorkspace';
import { useWorkspaces } from '@/hooks/useWorkspaces';
import { errorDetail } from '@/utils/errorDetail';
import { artifactTitle } from '@/utils/untitled';

type TrashDialogProps = {
  isOpen: boolean;
  onClose: () => void;
};

function shortDate(stamp?: string): string {
  if (!stamp) return '';
  const when = new Date(stamp);
  return Number.isNaN(when.getTime()) ? '' : when.toLocaleDateString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
  });
}

function titleOf(item: ArtifactResponse): string {
  return artifactTitle(item) || item.name || 'Untitled';
}

/** Mounted only while open, so a closed Trash reads nothing and needs no providers. */
export default function TrashDialog({ isOpen, onClose }: TrashDialogProps) {
  return isOpen ? <TrashContents onClose={onClose} /> : null;
}

function TrashContents({ onClose }: { onClose: () => void }) {
  const [items, setItems] = useState<ArtifactResponse[] | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const confirm = useConfirm();
  const { refreshArtifacts } = useWorkspace();
  const { activeWorkspaceId } = useWorkspaces();

  const load = useCallback(async () => {
    try {
      setItems(await listTrash());
    } catch (err) {
      setItems([]);
      toast.error('Could not load Trash', {
        description: errorDetail(err, err instanceof Error ? err.message : 'Unknown error'),
      });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const drop = (id: string) => setItems(prev => (prev ?? []).filter(i => String(i.id) !== id));

  const restore = async (item: ArtifactResponse) => {
    const id = String(item.id);
    setBusyId(id);
    try {
      await updateArtifact(id, { state: 'live' });
      drop(id);
      toast(`Restored "${titleOf(item)}"`);
      if (activeWorkspaceId) await refreshArtifacts(activeWorkspaceId);
    } catch (err) {
      toast.error('Could not restore it', {
        description: errorDetail(err, err instanceof Error ? err.message : 'Unknown error'),
      });
    } finally {
      setBusyId(null);
    }
  };

  const deleteForGood = async (item: ArtifactResponse) => {
    const confirmed = await confirm.confirm({
      title: CARD_CONFIRM.DELETE_PERMANENT_TITLE,
      description: CARD_CONFIRM.DELETE_PERMANENT_DESCRIPTION,
      confirmLabel: CARD_CONFIRM.DELETE_PERMANENT_CONFIRM,
      cancelLabel: BUTTON_LABELS.CANCEL,
    });
    if (!confirmed) return;
    const id = String(item.id);
    setBusyId(id);
    try {
      await deleteArtifact(id);
      drop(id);
    } catch (err) {
      toast.error('Could not delete it', {
        description: errorDetail(err, err instanceof Error ? err.message : 'Unknown error'),
      });
    } finally {
      setBusyId(null);
    }
  };

  return (
    <Dialog open onOpenChange={(open) => (open ? null : onClose())}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Trash</DialogTitle>
          <DialogDescription>
            What you delete stays here for {TRASH_RETENTION_DAYS} days, then it is deleted for good.
          </DialogDescription>
        </DialogHeader>

        {items === null && <p className="text-sm text-muted-foreground">Loading…</p>}
        {items !== null && items.length === 0 && (
          <p className="text-sm text-muted-foreground">Trash is empty.</p>
        )}
        {items !== null && items.length > 0 && (
          <ul className="divide-y max-h-[60vh] overflow-y-auto" aria-label="Trash">
            {items.map(item => {
              const id = String(item.id);
              return (
                <li key={id} className="flex items-center gap-3 py-2">
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">{titleOf(item)}</div>
                    <div className="text-xs text-muted-foreground">
                      Deleted {shortDate(item.trashed_time)}
                      {item.purge_after ? ` · gone for good on ${shortDate(item.purge_after)}` : ''}
                    </div>
                  </div>
                  <Button size="sm" variant="outline" disabled={busyId === id}
                          onClick={() => void restore(item)}>
                    Restore
                  </Button>
                  <Button size="sm" variant="destructive" disabled={busyId === id}
                          onClick={() => void deleteForGood(item)}>
                    Delete permanently
                  </Button>
                </li>
              );
            })}
          </ul>
        )}
      </DialogContent>
    </Dialog>
  );
}
