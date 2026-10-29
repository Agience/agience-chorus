import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import { CardContextItems } from '../CardContextItems';
import { WorkspacesContext, type WorkspacesContextType } from '@/context/workspaces/WorkspacesContext';
import type { Artifact } from '@/context/workspace/workspace.types';
import type { ContentTypeDefinition } from '@/registry/content-types';

vi.mock('../../ui/context-menu', () => ({
  ContextMenuItem: ({ children, onClick }: { children: React.ReactNode; onClick?: (e: React.MouseEvent) => void }) => (
    <button onClick={onClick}>{children}</button>
  ),
  ContextMenuSeparator: () => <hr />,
}));

const plainType = { actions: [] } as unknown as ContentTypeDefinition;
const WS = 'application/vnd.agience.workspace+json';

function renderWith(artifact: Artifact, openWorkspaceTab = vi.fn(), onAction = vi.fn()) {
  const tabs = { workspaces: [{ id: 'reg-ws', name: 'REG-WS' }], openWorkspaceTab } as unknown as WorkspacesContextType;
  render(
    <WorkspacesContext.Provider value={tabs}>
      <CardContextItems artifact={artifact} contentType={plainType} onAction={onAction} />
    </WorkspacesContext.Provider>,
  );
  return { openWorkspaceTab, onAction };
}

describe('CardContextItems', () => {
  // 2026-10-23, a tester found no way to share a workspace made as a card: it opened only in a
  // window, and the header's Share follows the selected tab.
  it('opens a workspace card as a tab', () => {
    const ws = { id: 'reg-ws', context: JSON.stringify({ content_type: WS, title: 'REG-WS' }), state: 'live' } as unknown as Artifact;
    const { openWorkspaceTab, onAction } = renderWith(ws);
    fireEvent.click(screen.getByText('Open as tab'));
    expect(openWorkspaceTab).toHaveBeenCalledWith('reg-ws');
    expect(onAction).not.toHaveBeenCalled();
  });

  it('offers no tab for a note, and no Edit that does nothing', () => {
    const note = { id: 'n1', context: JSON.stringify({ title: 'DELTA' }), state: 'live' } as unknown as Artifact;
    renderWith(note);
    expect(screen.queryByText('Open as tab')).toBeNull();
    expect(screen.queryByText('Edit')).toBeNull();
    expect(screen.getByText('Open')).toBeInTheDocument();
  });
});
