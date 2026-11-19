import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

import { CardContextItems } from '../CardContextItems';
import { LockedActionsContext } from '@/context/view/useLockedActions';
import type { Artifact } from '@/context/workspace/workspace.types';
import type { ContentTypeDefinition } from '@/registry/content-types';

vi.mock('../../ui/context-menu', () => ({
  ContextMenuItem: ({ children, onClick }: { children: React.ReactNode; onClick?: (e: React.MouseEvent) => void }) => (
    <button onClick={onClick}>{children}</button>
  ),
  ContextMenuSeparator: () => <hr />,
}));

const plainType = { actions: [] } as unknown as ContentTypeDefinition;
const live = { id: 'a1', allowed_actions: ['read', 'update', 'share'], context: '{}', content: '', state: 'live' } as unknown as Artifact;

describe('CardContextItems shows what the view withholds', () => {
  it('withholds the actions the view names for the member', () => {
    render(
      <LockedActionsContext.Provider value={{ a1: ['archive'] }}>
        <CardContextItems artifact={live} contentType={plainType} onAction={vi.fn()} />
      </LockedActionsContext.Provider>,
    );
    expect(screen.queryByText('Archive')).toBeNull();
    expect(screen.getByText('Open')).toBeInTheDocument();
  });

  it('offers them when the view withholds nothing from it', () => {
    render(
      <LockedActionsContext.Provider value={{ other: ['archive'] }}>
        <CardContextItems artifact={live} contentType={plainType} onAction={vi.fn()} />
      </LockedActionsContext.Provider>,
    );
    expect(screen.getByText('Archive')).toBeInTheDocument();
  });
});
