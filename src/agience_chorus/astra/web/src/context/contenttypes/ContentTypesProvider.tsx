/**
 * Hydrates the content-type registry from the platform (GET /types/all) once,
 * before any artifact UI renders. Gating here means every synchronous
 * getContentType() consumer sees the full, runtime-resolved registry — no
 * per-component re-render plumbing. Facet ships only generic viewers; the type
 * definitions (incl. which viewer + ui.record / resource_uri) come from the
 * platform, so Facet never compiles in server-owned types.
 */

import { useEffect, useState, type ReactNode } from 'react';
import { getResolvedTypes } from '@/api/contentTypes';
import { setRuntimeContentTypes } from '@/registry/content-types';

export function ContentTypesProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getResolvedTypes()
      .then((entries) => {
        if (!cancelled && entries.length) setRuntimeContentTypes(entries);
      })
      .catch((err) => {
        // Degrade to the build-time core primitives rather than blocking the app.
        console.error('ContentTypesProvider: failed to load types from platform', err);
      })
      .finally(() => {
        if (!cancelled) setReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!ready) {
    return (
      <div className="flex h-full w-full items-center justify-center text-sm text-gray-400">
        Loading…
      </div>
    );
  }
  return <>{children}</>;
}
