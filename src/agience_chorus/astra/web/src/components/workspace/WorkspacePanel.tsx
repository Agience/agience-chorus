/**
 * WorkspacePanel
 *
 * Right panel in the two-panel layout. Houses the active workspace's artifact
 * browser and all list-management UI.
 *
 * A thin structural wrapper around Browser: Browser owns the upload, filter,
 * and selection state, so this component only supplies layout and props.
 */
import Browser from '../browser/Browser';
import type { ActiveSource } from '../../types/workspace';
import type { Artifact } from '../../context/workspace/workspace.types';

// ─── Types ────────────────────────────────────────────────────────────────────

export interface WorkspacePanelProps {
  activeSource: ActiveSource;
  selectedArtifactId?: string | null;
  searchResultArtifacts?: Artifact[];
  onArtifactSelect?: (artifactId: string | null) => void;
  onOpenArtifact?: (artifact: Artifact, options?: { startInEditMode?: boolean }) => void;
}

// ─── Component ────────────────────────────────────────────────────────────────

export function WorkspacePanel({
  activeSource,
  selectedArtifactId,
  searchResultArtifacts,
  onArtifactSelect,
  onOpenArtifact,
}: WorkspacePanelProps) {
  return (
    <div className="flex flex-col h-full">
      <Browser
        activeSource={activeSource}
        selectedArtifactId={selectedArtifactId ?? undefined}
        searchResultArtifacts={searchResultArtifacts}
        onArtifactSelect={onArtifactSelect}
        onOpenArtifact={onOpenArtifact}
      />
    </div>
  );
}

export default WorkspacePanel;
