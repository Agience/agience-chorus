import { describe, expect, it } from 'vitest';
import { besideRect } from '../windowPlacement';

describe('besideRect', () => {
  it('places the window to the right of its opener when it fits', () => {
    expect(besideRect({ x: 40, y: 60, w: 600, h: 500 }, 600, 500, 1600, 900)).toEqual({ x: 652, y: 60 });
  });

  it('places it to the left when only the left has room', () => {
    expect(besideRect({ x: 900, y: 60, w: 600, h: 500 }, 600, 500, 1600, 900)).toEqual({ x: 288, y: 60 });
  });

  it('is null when neither side has room', () => {
    expect(besideRect({ x: 200, y: 60, w: 720, h: 500 }, 720, 500, 1200, 800)).toBeNull();
  });

  it('keeps the window on screen vertically', () => {
    expect(besideRect({ x: 40, y: 700, w: 600, h: 500 }, 600, 500, 1600, 900)?.y).toBe(384);
  });
});
