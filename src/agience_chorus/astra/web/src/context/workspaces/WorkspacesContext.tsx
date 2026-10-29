// context/workspaces/WorkspacesContext.tsx
import { createStrictContext } from '../../utils/createStrictContext';
import { Workspace } from '../workspace/workspace.types';

export interface WorkspacesContextType {
  workspaces: Workspace[];
  activeWorkspace: Workspace | null;
  activeWorkspaceId: string | null;  
  createWorkspace: (name: string, description: string, options?: { activate?: boolean }) => Promise<Workspace>;  
  updateWorkspace: (workspace: Partial<Workspace> & { id: string }) => Promise<void>;
  deleteWorkspace: (id: string) => Promise<void>;
  setActiveWorkspaceId: (id: string | null) => void;
  /** Open a workspace as a tab: docked if the tabs are an explicit list, and selected. */
  openWorkspaceTab: (id: string) => void;
}

export const [WorkspacesContext, useWorkspaces] =
  createStrictContext<WorkspacesContextType>('WorkspacesContext');
