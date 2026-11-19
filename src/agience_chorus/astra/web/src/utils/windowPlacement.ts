export type WindowRect = { x: number; y: number; w: number; h: number };

/** Options for opening an artifact's window. `from` is the window it was opened from, if any. */
export type OpenArtifactOptions = { startInEditMode?: boolean; from?: WindowRect };

const GAP = 12;
const EDGE = 16;

/**
 * Where a window of size w×h goes so it does not cover the window it was opened from: to its right
 * when that fits on screen, else to its left, top edges aligned. Null when neither side has room;
 * the window then takes the usual cascade.
 */
export function besideRect(
  from: WindowRect,
  w: number,
  h: number,
  vw: number,
  vh: number,
): { x: number; y: number } | null {
  const y = Math.max(EDGE, Math.min(from.y, vh - h - EDGE));
  const right = from.x + from.w + GAP;
  if (right + w <= vw - EDGE) return { x: right, y };
  const left = from.x - GAP - w;
  if (left >= EDGE) return { x: left, y };
  return null;
}
