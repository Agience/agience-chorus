// utils/inbox.ts
//
// Which workspace is a person's Inbox: their oldest own workspace, the rule Mantle provisions by
// (`seed_provisioning/user_provisioning._ensure_inbox_workspace`). It is not their user id: a
// new account's Inbox id is derived from it, and an older account's is a random UUID. 2026-10-17,
// on staging: with no workspace tab open, new cards were sent to the user id and answered 404.

import type { Workspace } from '@/api/types/workspace';

export function inboxWorkspaceId(workspaces: Workspace[], userId: string | null | undefined): string | null {
  if (!userId) return null;
  const own = workspaces.filter((w) => String(w.created_by) === String(userId));
  if (!own.length) return null;
  const oldest = [...own].sort((a, b) => String(a.created_time || '').localeCompare(String(b.created_time || '')))[0];
  return oldest?.id ?? null;
}
