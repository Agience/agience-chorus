// An edit still inside the debounce when its editor closes is saved, not dropped. 2026-10-14:
// renaming a card and closing its window within a second lost the new title.
import { describe, it, expect, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
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
});
