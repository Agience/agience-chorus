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
const result = (state: string): Artifact => ({ id: 'a1', context: '{}', content: '', state } as unknown as Artifact);

// 2026-10-29, a tester: an archived search result could be restored only by opening it.
describe('a search result', () => {
  it('offers Restore when it is archived', () => {
    const onAction = vi.fn();
    render(<CardContextItems artifact={result('archived')} contentType={plainType} onAction={onAction} isSearchResult />);
    fireEvent.click(screen.getByText('Restore'));
    expect(onAction).toHaveBeenCalledWith('restore', expect.objectContaining({ id: 'a1' }));
  });

  it('offers no Restore when it is live', () => {
    render(<CardContextItems artifact={result('live')} contentType={plainType} onAction={vi.fn()} isSearchResult />);
    expect(screen.queryByText('Restore')).toBeNull();
  });
});
