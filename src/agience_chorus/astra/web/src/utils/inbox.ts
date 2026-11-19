// utils/inbox.ts
//
// Which workspace is a person's Inbox. Mantle decides it and marks it in the workspace listing;
// this only reads the mark. It is not their user id: an Inbox id is its own.

import type { Workspace } from '@/api/types/workspace';

export function inboxWorkspaceId(workspaces: Workspace[]): string | null {
  return workspaces.find((w) => w.inbox)?.id ?? null;
}
