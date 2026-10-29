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
  /** Artifacts opened in a window from outside the active workspace (a container's window, a
   * search result). Kept here, apart from what the center panel shows, and patched by every edit. */
  openedArtifacts: Artifact[];
  /** Keep `artifact` as opened: its window reads it from here while it is outside the active list. */
  keepOpenedArtifact: (artifact: Artifact) => void;
  /** Whether this person may edit `artifact` here: it is live, and in the active workspace or opened
   * from where they reached it. The server's access check is the gate; a refusal is toasted. */
  isEditable: (artifact: Artifact | null | undefined) => boolean;
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
  /** Say that `ids` moved to Trash (`what` names them), with Undo and View Trash. */
  announceTrashed: (ids: string[], what: string) => void;
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
