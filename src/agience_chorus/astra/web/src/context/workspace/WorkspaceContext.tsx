// context/workspace/WorkspaceContext.tsx
import { createStrictContext } from '../../utils/createStrictContext';
import { MouseEvent } from 'react';
import { Artifact } from './workspace.types';
import { ArtifactCreate } from '../../api/types';


export interface WorkspaceContextType {
  artifacts: Artifact[];
  /** Currently displayed artifacts in the center panel (may be workspace, collection, or search results) */
  displayedArtifacts?: Artifact[];
  /** Setter for displayed artifacts so components like Browser can publish what is currently shown */
  setDisplayedArtifacts?: (artifacts: Artifact[]) => void;
  selectedArtifactIds: string[];
  addArtifact: (artifact: ArtifactCreate) => Promise<void>;
  addExistingArtifact: (artifact: Artifact) => void;
  /** Merge fields into an artifact in local state only; sends nothing to the server. */
  patchArtifactLocally: (artifact: Partial<Artifact>) => void;
  createArtifact: (artifact: ArtifactCreate, insertIndex?: number) => Promise<Artifact | null>;
  updateArtifact: (artifact: Partial<Artifact>) => Promise<void>;
  /** Unlink the artifact from the active workspace. */
  removeArtifact: (id: string) => Promise<void>;
  /** Move the artifact to Trash, restorable for 30 days; `announce: false` skips the Undo toast
   * (a bulk caller announces once). Resolves false when the server refuses. */
  deleteArtifact: (id: string, options?: { announce?: boolean }) => Promise<boolean>;
  /** Delete the artifact for good. Resolves false when the server refuses. */
  discardArtifact: (id: string) => Promise<boolean>;
  refreshArtifacts: (workspaceId: string) => Promise<void>;
  selectArtifact: (id: string, event: MouseEvent) => void;
  orderArtifacts: (orderedIds: string[]) => Promise<void>;
  /** Import collection-root artifacts into the active workspace and insert at a drop index */
  importArtifactsByRootIds: (rootIds: string[], insertIndex: number) => Promise<void>;
  selectAllArtifacts: () => void;
  unselectAllArtifacts: () => void;
  extractInformationFromArtifact: (sourceArtifactId: string, contextArtifactIds?: string[]) => Promise<void>;
  extractInformationFromSelection: (options?: { sourceArtifactId?: string }) => Promise<void>;
  createNewArtifact: () => void;
  registerNewArtifactHandler: (fn: (artifact: Artifact) => void) => void;  
}

export const [WorkspaceContext, useWorkspace] =
  createStrictContext<WorkspaceContextType>('WorkspaceContext');
