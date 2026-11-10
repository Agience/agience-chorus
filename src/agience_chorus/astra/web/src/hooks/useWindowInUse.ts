import { useEffect, useState } from 'react';

/** The marker every floating artifact window carries on its root (`FloatingCardWindow`). */
export const WINDOW_MARKER = '[data-floating-window]';

/**
 * Whether the person is working in a floating window: their last press (mouse, pen or touch, and
 * the right button that opens a context menu) landed inside one, and that window is still open.
 * A press anywhere else ends it. The workspace grid's selection bar stands aside while it holds
 * (BUG-019).
 */
export function useWindowInUse(): boolean {
  const [inUse, setInUse] = useState(false);
  useEffect(() => {
    function onPress(e: PointerEvent) {
      const target = e.target instanceof Element ? e.target : null;
      setInUse(Boolean(target?.closest(WINDOW_MARKER)));
    }
    // A window closed while in use leaves the grid as the place the person works.
    const observer = new MutationObserver(() => {
      setInUse((was) => was && document.querySelector(WINDOW_MARKER) !== null);
    });
    document.addEventListener('pointerdown', onPress, true);
    observer.observe(document.body, { childList: true, subtree: true });
    return () => {
      document.removeEventListener('pointerdown', onPress, true);
      observer.disconnect();
    };
  }, []);
  return inUse;
}
