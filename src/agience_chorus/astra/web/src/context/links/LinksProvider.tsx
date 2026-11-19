import { useCallback, useMemo, useState, type ReactNode } from 'react';

import { LinksDialog } from '@/components/common/LinksDialog';

import { LinksContext } from './useLinks';

/** The named links of any artifact, opened from its context menu. */
export function LinksProvider({ children }: { children: ReactNode }) {
  const [id, setId] = useState<string | null>(null);
  const openLinks = useCallback((artifactId: string) => { if (artifactId) setId(String(artifactId)); }, []);
  const value = useMemo(() => ({ openLinks }), [openLinks]);
  return (
    <LinksContext.Provider value={value}>
      {children}
      {id && <LinksDialog open onOpenChange={(o) => { if (!o) setId(null); }} artifactId={id} />}
    </LinksContext.Provider>
  );
}
