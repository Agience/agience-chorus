import { createContext, useContext } from 'react';

export interface LinksContextValue { openLinks: (artifactId: string) => void }

export const LinksContext = createContext<LinksContextValue | null>(null);

/** `openLinks(id)`, or null outside a LinksProvider (a host without it offers no Links item). */
export function useLinks(): LinksContextValue | null {
  return useContext(LinksContext);
}
