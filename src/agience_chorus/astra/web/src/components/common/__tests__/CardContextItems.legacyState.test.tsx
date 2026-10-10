import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import { CardContextItems } from '../CardContextItems';
import type { Artifact } from '@/context/workspace/workspace.types';
import type { ContentTypeDefinition } from '@/registry/content-types';

vi.mock('../../ui/context-menu', () => ({
  ContextMenuItem: ({ children, onClick }: { children: React.ReactNode; onClick?: (e: React.MouseEvent) => void }) => (
    <button onClick={onClick}>{children}</button>
  ),
  ContextMenuSeparator: () => <hr />,
}));

const plainType = { actions: [] } as unknown as ContentTypeDefinition;

// A store written before the live/archived rule can still hand the UI these values.
const legacy = (state: string): Artifact =>
  ({ id: 'a1', context: '{}', content: '', state } as unknown as Artifact);

describe('CardContextItems with a legacy state', () => {
  it.each(['committed', 'draft'])('a %s card renders as live: Archive offered, no Revert, no Restore', (state) => {
    const onAction = vi.fn();
    render(<CardContextItems artifact={legacy(state)} contentType={plainType} onAction={onAction} />);

    expect(screen.getByText('Archive')).toBeInTheDocument();
    expect(screen.getByText('Edit')).toBeInTheDocument();
    expect(screen.queryByText(/Revert/)).toBeNull();
    expect(screen.queryByText('Restore')).toBeNull();

    fireEvent.click(screen.getByText('Archive'));
    expect(onAction).toHaveBeenCalledWith('archive', expect.objectContaining({ id: 'a1' }));
  });

  it('an archived card offers Restore and not Archive', () => {
    render(<CardContextItems artifact={legacy('archived')} contentType={plainType} onAction={vi.fn()} />);

    expect(screen.getByText('Restore')).toBeInTheDocument();
    expect(screen.queryByText('Archive')).toBeNull();
  });
});
