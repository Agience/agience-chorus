import { createContext, useContext } from 'react';

/** The actions the view withholds from each member, by its key, as Crystal runs it from the
 *  members' types. A member outside a view has none withheld. */
export const LockedActionsContext = createContext<Record<string, string[]>>({});

/** The actions withheld from `artifact` now. */
export function useLockedActions(artifact: { id?: string | number | null; root_id?: string | number | null }): string[] {
  return useContext(LockedActionsContext)[String(artifact.root_id ?? artifact.id)] ?? [];
}
