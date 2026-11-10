// BUG-016 (2026-11-10): every workspace the person reaches and has not docked, their own and those
// shared with them, is offered by name, since search returns no workspace.
import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import BrowserHeader from '../BrowserHeader';

const openWorkspaceTab = vi.fn();
let docked: string[] | undefined = ['ws-1'];
const WORKSPACES = [
  { id: 'ws-1', name: 'Inbox' },
  { id: 'ws-2', name: 'Shared with me' },
  { id: 'ws-3', name: 'Agience' },
];

vi.mock('../../../hooks/useWorkspace', () => ({ useWorkspace: () => ({ createArtifact: vi.fn() }) }));
vi.mock('../../../hooks/useWorkspaces', () => ({
  useWorkspaces: () => ({
    workspaces: WORKSPACES, activeWorkspace: WORKSPACES[0], setActiveWorkspaceId: vi.fn(),
    openWorkspaceTab,
  }),
}));
vi.mock('../../../hooks/usePreferences', () => ({
  usePreferences: () => ({
    preferences: { browser: docked ? { dockedWorkspaceCardIds: docked } : {} },
    updatePreferences: vi.fn().mockResolvedValue(undefined), isLoading: false,
  }),
}));
vi.mock('../../../api/collections', () => ({ listCollections: vi.fn().mockResolvedValue([]) }));
vi.mock('@/components/ui/dropdown-menu', () => ({
  DropdownMenu: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DropdownMenuTrigger: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DropdownMenuContent: ({ children }: { children: React.ReactNode }) => <div data-testid="dock-menu">{children}</div>,
  DropdownMenuItem: ({ children, onClick }: { children: React.ReactNode; onClick?: () => void }) =>
    <button type="button" onClick={onClick}>{children}</button>,
}));

const header = () => render(
  <BrowserHeader activeSource={null} onToggleFilters={() => {}} filtersOpen={false} hasActiveFilter={false}
                 activeFilter="all" viewMode="grid" onViewModeChange={() => {}} />,
);

describe('the dock menu', () => {
  beforeEach(() => { openWorkspaceTab.mockReset(); });

  it('offers each reachable workspace not docked, by name, and docks the one chosen', () => {
    docked = ['ws-1'];
    header();
    const menu = screen.getByTestId('dock-menu');
    expect(Array.from(menu.querySelectorAll('button')).map(b => b.textContent)).toEqual(['Agience', 'Shared with me']);
    fireEvent.click(screen.getByText('Shared with me'));
    expect(openWorkspaceTab).toHaveBeenCalledWith('ws-2');
  });

  it('with nothing docked, the empty bar offers them all', () => {
    docked = [];
    header();
    expect(screen.getByText('Choose a workspace to dock.')).toBeDefined();
    expect(screen.getByTestId('dock-menu').querySelectorAll('button')).toHaveLength(3);
  });

  it('is not shown when every workspace is a tab', () => {
    docked = undefined;
    header();
    expect(screen.queryByTestId('dock-menu')).toBeNull();
  });
});
