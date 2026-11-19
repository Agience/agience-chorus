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

const withState = (state: string): Artifact =>
  ({ id: 'a1', allowed_actions: ['read', 'update', 'share'], context: '{}', content: '', state } as unknown as Artifact);

describe('CardContextItems by state', () => {
  it('a live card offers Archive, no Revert, no Restore', () => {
    const onAction = vi.fn();
    render(<CardContextItems artifact={withState('live')} contentType={plainType} onAction={onAction} />);

    expect(screen.getByText('Archive')).toBeInTheDocument();
    expect(screen.getByText('Open')).toBeInTheDocument();
    expect(screen.queryByText(/Revert/)).toBeNull();
    expect(screen.queryByText('Restore')).toBeNull();

    fireEvent.click(screen.getByText('Archive'));
    expect(onAction).toHaveBeenCalledWith('archive', expect.objectContaining({ id: 'a1' }));
  });

  it('an archived card offers Restore and not Archive', () => {
    render(<CardContextItems artifact={withState('archived')} contentType={plainType} onAction={vi.fn()} />);

    expect(screen.getByText('Restore')).toBeInTheDocument();
    expect(screen.queryByText('Archive')).toBeNull();
  });
});
