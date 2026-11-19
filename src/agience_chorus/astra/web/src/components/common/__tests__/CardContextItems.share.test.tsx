import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import type { Artifact } from '@/context/workspace/workspace.types';
import type { ContentTypeDefinition } from '@/registry/content-types';

// FR-030 (John, 2026-11-14): "Should be able to share any artifact." Every artifact's context menu
// offers Share, which opens the one first-party Share dialog for that artifact's own id; no host
// handles it, and any type gets it, whatever actions it declares.
vi.mock('../../ui/context-menu', () => ({
  ContextMenuItem: ({ children, onClick }: { children: React.ReactNode; onClick?: (e: React.MouseEvent) => void }) => (
    <button onClick={onClick}>{children}</button>
  ),
  ContextMenuSeparator: () => <hr />,
}));
let shareCtx: { openShare: ReturnType<typeof vi.fn> } | null = null;
vi.mock('@/context/share/useShare', () => ({ useShare: () => shareCtx }));

import { CardContextItems } from '../CardContextItems';

const plainType = { actions: [] } as unknown as ContentTypeDefinition;
const declaredType = { actions: [{ id: 'run', label: 'Run now', states: ['live'] }] } as unknown as ContentTypeDefinition;
const note = (state = 'live') =>
  ({ id: 'note-9', allowed_actions: ['read', 'update', 'share'], context: JSON.stringify({ title: 'Meeting notes', content_type: 'text/markdown' }), state }) as unknown as Artifact;

describe('CardContextItems — Share on any artifact', () => {
  beforeEach(() => { shareCtx = { openShare: vi.fn() }; });

  it('opens Share for this artifact by its own id, not through the host', () => {
    const onAction = vi.fn();
    render(<CardContextItems artifact={note()} contentType={plainType} onAction={onAction} />);
    fireEvent.click(screen.getByText('Share…'));
    expect(shareCtx!.openShare).toHaveBeenCalledWith('note-9');
    expect(onAction).not.toHaveBeenCalled();
  });

  it('is offered on a type that declares its own actions too', () => {
    render(<CardContextItems artifact={note()} contentType={declaredType} onAction={vi.fn()} />);
    expect(screen.getByText('Run now')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Share…'));
    expect(shareCtx!.openShare).toHaveBeenCalledWith('note-9');
  });

  it('is not offered for an archived artifact, nor where no Share dialog is mounted', () => {
    const { unmount } = render(<CardContextItems artifact={note('archived')} contentType={plainType} onAction={vi.fn()} />);
    expect(screen.queryByText('Share…')).toBeNull();
    unmount();
    shareCtx = null;
    render(<CardContextItems artifact={note()} contentType={plainType} onAction={vi.fn()} />);
    expect(screen.queryByText('Share…')).toBeNull();
  });
});
