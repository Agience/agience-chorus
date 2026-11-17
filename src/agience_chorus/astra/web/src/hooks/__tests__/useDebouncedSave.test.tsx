// An edit still inside the debounce when its editor closes is saved, not dropped. A save the
// store refuses is never shown as saved (BUG-118).
import { describe, it, expect, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useDebouncedSave } from '../useDebouncedSave';

vi.mock('react-hot-toast', () => ({ default: { error: vi.fn() } }));

describe('useDebouncedSave', () => {
  it('saves a pending edit when the editor unmounts', () => {
    const onSave = vi.fn(() => Promise.resolve());
    const { rerender, unmount } = renderHook(({ v }) => useDebouncedSave(v, { delay: 1000, onSave }),
      { initialProps: { v: 'Untitled' } });
    rerender({ v: 'Renamed' });
    unmount();
    expect(onSave).toHaveBeenCalledWith('Renamed');
  });

  it('saves nothing on unmount when nothing changed', () => {
    const onSave = vi.fn(() => Promise.resolve());
    const { unmount } = renderHook(() => useDebouncedSave('same', { delay: 1000, onSave }));
    unmount();
    expect(onSave).not.toHaveBeenCalled();
  });

  it('saves nothing on unmount when disabled', () => {
    const onSave = vi.fn(() => Promise.resolve());
    const { rerender, unmount } = renderHook(({ v }) => useDebouncedSave(v, { delay: 1000, onSave, enabled: false }),
      { initialProps: { v: 'a' } });
    rerender({ v: 'b' });
    unmount();
    expect(onSave).not.toHaveBeenCalled();
  });

  it('shows a refused save as failed, never saved, and saves again on the next edit', async () => {
    vi.useFakeTimers();
    try {
      const onSave = vi.fn((_v: string) => Promise.resolve(false));
      const { result, rerender } = renderHook(({ v }) => useDebouncedSave(v, { delay: 100, onSave }),
        { initialProps: { v: 'a' } });
      rerender({ v: 'b' });
      await act(async () => { await vi.advanceTimersByTimeAsync(150); });
      expect(onSave).toHaveBeenCalledWith('b');
      expect(result.current.saveFailed).toBe(true);
      expect(result.current.lastSaved).toBeNull();

      onSave.mockImplementation(() => Promise.resolve(true));
      rerender({ v: 'c' });
      await act(async () => { await vi.advanceTimersByTimeAsync(150); });
      expect(result.current.saveFailed).toBe(false);
      expect(result.current.lastSaved).not.toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('shows a thrown save as failed', async () => {
    vi.useFakeTimers();
    try {
      const onSave = vi.fn((_v: string) => Promise.reject(new Error('404')));
      const { result, rerender } = renderHook(({ v }) => useDebouncedSave(v, { delay: 100, onSave }),
        { initialProps: { v: 'a' } });
      rerender({ v: 'b' });
      await act(async () => { await vi.advanceTimersByTimeAsync(150); });
      expect(result.current.saveFailed).toBe(true);
      expect(result.current.lastSaved).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});
