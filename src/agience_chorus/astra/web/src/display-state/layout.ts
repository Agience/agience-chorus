/**
 * On-screen geometry: where things sit in the viewer's window. These helpers take rectangles the
 * browser measured and know nothing of what is drawn in them.
 */

type Box = { readonly bottom: number; readonly right: number };

/** The right edge of the bottom row: the boxes whose bottom is within `tolerance` of the lowest. */
export function bottomRowRight(boxes: readonly Box[], tolerance = 8): number {
  let bottom = -Infinity;
  for (const box of boxes) bottom = Math.max(bottom, box.bottom);
  let right = 0;
  for (const box of boxes) if (Math.abs(box.bottom - bottom) < tolerance) right = Math.max(right, box.right);
  return right;
}
