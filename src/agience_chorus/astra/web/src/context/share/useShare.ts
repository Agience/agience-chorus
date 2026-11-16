import { createContext, useContext } from 'react';

export interface ShareContextValue { openShare: (artifactId: string) => void }

export const ShareContext = createContext<ShareContextValue | null>(null);

/** `openShare(id)`, or null outside a ShareProvider (a host without Share offers no Share item). */
export function useShare(): ShareContextValue | null {
  return useContext(ShareContext);
}
