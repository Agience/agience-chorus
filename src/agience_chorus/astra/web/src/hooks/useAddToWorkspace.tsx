// hooks/useAddToWorkspace.tsx
//
// "Add to workspace" (BUG-075): ask which workspace, link the artifact there (the link a drop onto
// a workspace makes; it stays where it is too) and say where it went. One handler for every place
// that offers it: the centre's results and the search panel's alike. 2026-11-15, the Tester: the
// search panel's own handler only added it to the open workspace's list in this window.
import { useCallback, useState, type ReactNode } from 'react';
import { toast } from 'sonner';
import WorkspacePicker from '@/components/modals/WorkspacePicker';
import { importCollectionArtifactToWorkspace } from '@/api/workspaces';
import type { Artifact } from '@/context/workspace/workspace.types';
import { useWorkspace } from '@/hooks/useWorkspace';
import { useWorkspaces } from '@/hooks/useWorkspaces';
import { errorDetail } from '@/utils/errorDetail';
import { workspaceLabel } from '@/utils/workspaceLabels';

export function useAddToWorkspace(): { addToWorkspace: (artifact: Artifact) => void; picker: ReactNode } {
  const { workspaces, activeWorkspace } = useWorkspaces();
  const { addExistingArtifact } = useWorkspace();
  const [adding, setAdding] = useState<Artifact | null>(null);

  const addTo = useCallback(async (targetId: string) => {
    const artifact = adding;
    setAdding(null);
    if (!artifact) return;
    const target = workspaces.find((w) => String(w.id) === String(targetId));
    const label = target ? workspaceLabel(target) : 'the workspace';
    try {
      const linked = await importCollectionArtifactToWorkspace(targetId, String(artifact.root_id ?? artifact.id));
      if (String(targetId) === String(activeWorkspace?.id)) addExistingArtifact(linked as unknown as Artifact);
      toast.success(`Added to ${label}`);
    } catch (err) {
      toast.error(`Could not add it to ${label}`, { description: errorDetail(err, '') || undefined });
    }
  }, [activeWorkspace?.id, addExistingArtifact, adding, workspaces]);

  const picker = (
    <WorkspacePicker
      open={adding !== null}
      title="Add to workspace"
      description="It stays where it is too; the workspace shows it as well."
      workspaces={workspaces}
      currentId={activeWorkspace?.id}
      onPick={(id) => { void addTo(id); }}
      onClose={() => setAdding(null)}
    />
  );
  return { addToWorkspace: setAdding, picker };
}
