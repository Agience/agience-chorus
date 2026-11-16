import { useCallback, useMemo, useState, type ReactNode } from 'react';

import { ShareDialog } from '@/components/common/ShareDialog';

/** Share any artifact (FR-030). Opened only from first-party UI: an artifact's window header and
 *  its context menu. A view, an MCP app or an iframe never reaches it, so no artifact view can open
 *  Share for an id it chose. The dialog loads the item's own name by that id. */
import { ShareContext } from './useShare';

export function ShareProvider({ children }: { children: ReactNode }) {
  const [id, setId] = useState<string | null>(null);
  const openShare = useCallback((artifactId: string) => { if (artifactId) setId(String(artifactId)); }, []);
  const value = useMemo(() => ({ openShare }), [openShare]);
  return (
    <ShareContext.Provider value={value}>
      {children}
      {id && <ShareDialog open onOpenChange={(o) => { if (!o) setId(null); }} resourceId={id} />}
    </ShareContext.Provider>
  );
}
