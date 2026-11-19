import { useEffect, useState } from 'react';

/** Below this width the app shows one panel at a time and the top bar folds its icons. */
export const NARROW_VIEWPORT_PX = 640;

const QUERY = `(max-width: ${NARROW_VIEWPORT_PX - 1}px)`;

function matches(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false;
  return window.matchMedia(QUERY).matches;
}

/** Whether the viewport is narrower than {@link NARROW_VIEWPORT_PX}, kept current as it resizes. */
export function useNarrowViewport(): boolean {
  const [narrow, setNarrow] = useState(matches);
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    const mql = window.matchMedia(QUERY);
    const onChange = () => setNarrow(mql.matches);
    onChange();
    mql.addEventListener('change', onChange);
    return () => mql.removeEventListener('change', onChange);
  }, []);
  return narrow;
}
