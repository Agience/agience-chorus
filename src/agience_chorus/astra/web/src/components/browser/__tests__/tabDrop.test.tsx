// BUG-018 (2026-11-10): artifacts dropped on a workspace's tab go into that workspace. The drop fell
// through to the tab bar, which made a new workspace of them.
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import BrowserHeader from '../BrowserHeader';
import { AGIENCE_DRAG_CONTENT_TYPE } from '@/dnd/agienceDrag';

const WORKSPACES = [{ id: 'ws-1', name: 'Inbox' }, { id: 'ws-2', name: 'Agience' }];
vi.mock('../../../hooks/useWorkspace', () => ({ useWorkspace: () => ({ createArtifact: vi.fn() }) }));
vi.mock('../../../hooks/useWorkspaces', () => ({
  useWorkspaces: () => ({ workspaces: WORKSPACES, activeWorkspace: WORKSPACES[0],
                          setActiveWorkspaceId: vi.fn(), openWorkspaceTab: vi.fn() }),
}));
vi.mock('../../../hooks/usePreferences', () => ({
  usePreferences: () => ({ preferences: {}, updatePreferences: vi.fn(), isLoading: false }),
}));
vi.mock('../../../api/collections', () => ({ listCollections: vi.fn().mockResolvedValue([]) }));

function dataTransfer(ids: string[]) {
  const data: Record<string, string> = {
    [AGIENCE_DRAG_CONTENT_TYPE]: JSON.stringify({ kind: 'artifacts', ids }),
  };
  return { types: Object.keys(data), getData: (t: string) => data[t] ?? '', dropEffect: 'none' };
}

describe('a drop on a workspace tab', () => {
  it('goes into that workspace, and never makes a new one', () => {
    const onDropOnTab = vi.fn();
    const onDropWorkspace = vi.fn();
    render(
      <BrowserHeader activeSource={null} onToggleFilters={() => {}} filtersOpen={false} hasActiveFilter={false}
                     activeFilter="all" viewMode="grid" onViewModeChange={() => {}}
                     onDropOnTab={onDropOnTab} onDropWorkspace={onDropWorkspace} />,
    );
    const tab = screen.getByTestId('tab-ws-2');
    fireEvent.dragOver(tab, { dataTransfer: dataTransfer(['card-1']) });
    fireEvent.drop(tab, { dataTransfer: dataTransfer(['card-1', 'card-2']) });
    expect(onDropOnTab).toHaveBeenCalledWith('ws-2', ['card-1', 'card-2']);
    expect(onDropWorkspace).not.toHaveBeenCalled();
  });

  it('a right-click on a tab asks to delete that workspace (BUG-039)', () => {
    const onDeleteWorkspace = vi.fn();
    render(
      <BrowserHeader activeSource={null} onToggleFilters={() => {}} filtersOpen={false} hasActiveFilter={false}
                     activeFilter="all" viewMode="grid" onViewModeChange={() => {}}
                     onDeleteWorkspace={onDeleteWorkspace} />,
    );
    fireEvent.contextMenu(screen.getByRole('tab', { name: 'Agience' }));
    expect(onDeleteWorkspace).toHaveBeenCalledWith('ws-2');
  });
});
