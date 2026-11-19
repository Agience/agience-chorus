// The selection bar: one-word labels that never name the container; less used actions open from More,
// where Remove names its container because a phone has no hover title.
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import MultiCardToolbar from '../MultiCardToolbar';

const props = {
  selectedCount: 1,
  onArchive: vi.fn(),
  onAddTags: vi.fn(),
  onMove: vi.fn(),
  onDelete: vi.fn(),
  onDrop: vi.fn(),
  onClear: vi.fn(),
  canDelete: true,
  hasLive: true,
  dropTitle: 'Remove from Untitled workspace 2',
};

describe('The selection bar', () => {
  it('labels each action with one short verb', () => {
    render(<MultiCardToolbar {...props} />);
    const bar = screen.getByRole('toolbar', { name: '1 selected' });
    const labels = within(bar).getAllByRole('button').map(b => b.textContent?.trim()).filter(Boolean);
    expect(labels).toEqual(['Archive', 'Tag', 'Collect', 'Remove', 'Delete']);
    for (const b of within(bar).getAllByRole('button')) {
      expect(b.textContent).not.toContain('Untitled workspace');
      expect(b.className).toContain('flex-shrink-0');
    }
    expect(within(bar).getByRole('button', { name: 'Remove' }).getAttribute('title')).toBe(
      'Remove from Untitled workspace 2',
    );
  });

  it('offers the less used actions from More', () => {
    render(<MultiCardToolbar {...props} />);
    fireEvent.keyDown(screen.getByRole('button', { name: 'More actions' }), { key: 'Enter' });
    const items = screen.getAllByRole('menuitem').map(i => i.textContent?.trim());
    expect(items).toEqual(['Collect', 'Remove from Untitled workspace 2', 'Delete']);
    const remove = screen.getByRole('menuitem', { name: 'Remove from Untitled workspace 2' });
    expect(remove.getAttribute('title')).toBe('Remove from Untitled workspace 2');
    expect(remove.querySelector('.truncate')).toBeTruthy();
    fireEvent.click(remove);
    expect(props.onDrop).toHaveBeenCalled();
  });
});
