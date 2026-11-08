// 2026-10-31, a tester: the archived view's bulk toolbar had no Restore, though the right-click menu's
// Restore acted on the whole selection.
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import MultiCardToolbar from '../MultiCardToolbar';

const base = {
  selectedCount: 2,
  onArchive: vi.fn(),
  onAddTags: vi.fn(),
  onMove: vi.fn(),
  onDelete: vi.fn(),
  onDrop: vi.fn(),
  onClear: vi.fn(),
  canDelete: false,
};

describe('The bulk toolbar', () => {
  it('offers Restore when the selection holds archived artifacts', async () => {
    const onRestore = vi.fn();
    render(<MultiCardToolbar {...base} hasLive={false} hasArchived onRestore={onRestore} />);
    await userEvent.setup().click(screen.getByRole('button', { name: /restore/i }));
    expect(onRestore).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('button', { name: /^archive$/i })).toBeNull();
  });

  it('offers no Restore when nothing selected is archived', () => {
    render(<MultiCardToolbar {...base} hasLive hasArchived={false} onRestore={vi.fn()} />);
    expect(screen.queryByRole('button', { name: /restore/i })).toBeNull();
  });
});
