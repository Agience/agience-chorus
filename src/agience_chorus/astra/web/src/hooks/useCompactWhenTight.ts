import { useLayoutEffect, useRef, useState, type RefObject } from 'react';

/**
 * Whether a row should drop its button labels. A row that already fits keeps them. A row whose
 * content is wider than its room drops them. A compact row brings them back only once the room
 * left over would hold the labels again, so the row never flips back and forth at one width.
 */
export function nextCompact(compact: boolean, content: number, room: number, labelWidth: number): boolean {
  if (!compact) return content > room;
  return room - content < labelWidth;
}

/**
 * Watches a row whose `content` must fit in `room` next to a button `group`. The hook returns true
 * when the group should show icons only, which gives the room back to the content.
 */
export function useCompactWhenTight(
  roomRef: RefObject<HTMLElement | null>,
  contentRef: RefObject<HTMLElement | null>,
  groupRef: RefObject<HTMLElement | null>,
): boolean {
  const [compact, setCompact] = useState(false);
  const compactRef = useRef(false);
  const fullGroupWidth = useRef(0);

  useLayoutEffect(() => {
    const room = roomRef.current;
    const content = contentRef.current;
    const group = groupRef.current;
    if (!room || !content || !group || typeof ResizeObserver === 'undefined') return;

    const check = () => {
      const was = compactRef.current;
      if (!was) fullGroupWidth.current = group.offsetWidth;
      const labelWidth = was ? fullGroupWidth.current - group.offsetWidth : 0;
      const next = nextCompact(was, content.offsetWidth, room.clientWidth, labelWidth);
      if (next !== was) {
        compactRef.current = next;
        setCompact(next);
      }
    };

    const observer = new ResizeObserver(check);
    observer.observe(room);
    observer.observe(content);
    observer.observe(group);
    check();
    return () => observer.disconnect();
  }, [roomRef, contentRef, groupRef]);

  return compact;
}
