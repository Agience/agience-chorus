// api/types/workspace.ts

export interface WorkspaceCreate {
  name: string;
  description: string;
}

export interface WorkspaceResponse {
  id: string;
  name: string;
  description: string;
  created_by: string;
  created_time: string;
  modified_time: string;
  context?: Record<string, unknown>;
  order_key?: string;
  /** The actions Mantle allows the caller on it; the Facet offers only these. */
  allowed_actions?: string[];
  /** Mantle marks the listed workspace that is the caller's Inbox. */
  inbox?: boolean;
  /** Where another listed workspace shares this name: how much of `created_time` tells them apart. */
  label_at?: 'day' | 'minute' | 'second';
  /** Where even that matches: its place, from 2, in the order they were made. */
  label_n?: number;
}

export interface WorkspaceUpdate {
  name?: string;
  description?: string;
  /** The whole client context, as `stringifyArtifactContext` writes it: a rename sets its title. */
  context?: string;
}

export type Workspace = WorkspaceResponse;