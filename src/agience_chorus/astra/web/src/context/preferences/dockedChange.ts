// The docked tabs are one list the server replaces whole (`PATCH /auth/me/preferences` replaces each
// top-level key), and every writer sends it built from what its own page last read. A second tab or
// device holding an older copy wrote its list back and undocked what had been docked since
// (BUG-016, 2026-11-10: John's docked workspaces vanished). So a change to the list is applied as
// what this page added and removed, to the list the server holds now.
import type { Preferences } from './preferences.types';

const docked = (prefs: Partial<Preferences> | undefined): string[] | undefined => {
  const raw = (prefs?.browser as { dockedWorkspaceCardIds?: unknown } | undefined)?.dockedWorkspaceCardIds;
  return Array.isArray(raw) ? raw.map(String) : undefined;
};

/** `newPrefs` with its docked list rebased on the server's: this page's additions and removals,
 *  against the list it last read (`local`), applied to the list `read` returns now. */
export async function withDockedChange(newPrefs: Partial<Preferences>, local: Preferences,
                                       read: () => Promise<Preferences>): Promise<Partial<Preferences>> {
  const next = docked(newPrefs);
  if (!next) return newPrefs;
  const before = docked(local) ?? [];
  const added = next.filter(id => !before.includes(id));
  const removed = before.filter(id => !next.includes(id));
  let server: Preferences;
  try { server = await read(); } catch { return newPrefs; }
  const now = docked(server);
  if (!now) return newPrefs;
  const rebased = [...now.filter(id => !removed.includes(id)), ...added.filter(id => !now.includes(id))];
  return {
    ...newPrefs,
    browser: { ...((server.browser as object) || {}), ...((newPrefs.browser as object) || {}),
               dockedWorkspaceCardIds: rebased },
  };
}
