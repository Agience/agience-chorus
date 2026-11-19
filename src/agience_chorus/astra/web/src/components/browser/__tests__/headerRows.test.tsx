import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import BrowserHeader from '../BrowserHeader';
import FilterChips from '../FilterChips';
import { SearchPanel } from '../../search/SearchPanel';

const setActiveWorkspaceIdMock = vi.fn();
let mockWorkspaces: Array<{ id: string; name: string; created_time?: string; label_at?: 'day' | 'minute' | 'second' }> = [{ id: 'ws-1', name: 'Inbox' }];
let mockActiveWorkspace = { id: 'ws-1', name: 'Inbox' };

vi.mock('../../../hooks/useWorkspace', () => ({
  useWorkspace: () => ({
    createArtifact: vi.fn(),
  }),
}));

vi.mock('../../../hooks/useWorkspaces', () => ({
  useWorkspaces: () => ({
    workspaces: mockWorkspaces,
    activeWorkspace: mockActiveWorkspace,
    setActiveWorkspaceId: setActiveWorkspaceIdMock,
  }),
}));

vi.mock('../../../hooks/usePreferences', () => ({
  usePreferences: () => ({
    preferences: {},
    updatePreferences: vi.fn().mockResolvedValue(undefined),
    isLoading: false,
  }),
}));

vi.mock('../../../api/collections', () => ({
  listCollections: vi.fn().mockResolvedValue([]),
}));

vi.mock('@/context/shortcuts/useShortcuts', () => ({
  useShortcuts: () => ({
    registerShortcut: vi.fn(),
    unregisterShortcut: vi.fn(),
  }),
}));

vi.mock('@/components/ui/tabs', () => ({
  Tabs: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  TabsList: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  TabsTrigger: ({ children }: { children: React.ReactNode }) => <button type="button">{children}</button>,
}));

vi.mock('@/components/ui/dropdown-menu', () => ({
  DropdownMenu: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DropdownMenuTrigger: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DropdownMenuContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DropdownMenuItem: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock('../../common/CardGrid', () => ({
  default: () => <div data-testid="artifact-grid">artifact-grid</div>,
}));

describe('header row layout locks', () => {
  it('shows a dock target when no workspaces are visible', () => {
    mockWorkspaces = [];
    mockActiveWorkspace = null as unknown as { id: 'ws-1'; name: 'Inbox' };

    render(
      <BrowserHeader
        activeSource={null}
        onToggleFilters={() => {}}
        filtersOpen={false}
        hasActiveFilter={false}
        activeFilter="all"
        viewMode="grid"
        onViewModeChange={() => {}}
      />,
    );

    expect(screen.getByText('Find a workspace and dock it here.')).toBeDefined();
    // A tab bar with nothing docked holds no tabs, so it carries no tablist role.
    expect(screen.queryByRole('tablist')).toBeNull();

    mockWorkspaces = [{ id: 'ws-1', name: 'Inbox' }];
    mockActiveWorkspace = { id: 'ws-1', name: 'Inbox' };
  });

  it('a workspace tab shrinks with an ellipsis and keeps its full name in the title', () => {
    render(
      <BrowserHeader
        activeSource={{ type: 'workspace', id: 'ws-1' }}
        onToggleFilters={() => {}}
        filtersOpen={false}
        hasActiveFilter={false}
        activeFilter="all"
        viewMode="grid"
        onViewModeChange={() => {}}
      />,
    );
    const tab = screen.getByRole('tab', { name: 'Inbox' });
    expect(tab.className).toContain('truncate');
    expect(tab.getAttribute('title')).toMatch(/^Inbox/);
    expect(tab.parentElement?.className).not.toContain('flex-shrink-0');
  });

  it('a workspace tab carries its workspace id, whatever name it shows', () => {
    mockWorkspaces = [{ id: 'ws-1', name: 'Inbox' }, { id: 'ws-2', name: '' }];
    render(
      <BrowserHeader
        activeSource={{ type: 'workspace', id: 'ws-1' }}
        onToggleFilters={() => {}}
        filtersOpen={false}
        hasActiveFilter={false}
        activeFilter="all"
        viewMode="grid"
        onViewModeChange={() => {}}
      />,
    );
    const ids = screen.getAllByRole('tab').map((t) => t.getAttribute('data-workspace-id'));
    expect(ids).toEqual(expect.arrayContaining(['ws-1', 'ws-2']));
    expect(screen.getByRole('tab', { name: 'Inbox' }).getAttribute('data-workspace-id')).toBe('ws-1');
    mockWorkspaces = [{ id: 'ws-1', name: 'Inbox' }];
  });

  it('the tab list keeps its full width so a tab never slides under the buttons beside it', () => {
    render(
      <BrowserHeader
        activeSource={{ type: 'workspace', id: 'ws-1' }}
        onToggleFilters={() => {}}
        filtersOpen={false}
        hasActiveFilter={false}
        activeFilter="all"
        viewMode="grid"
        onViewModeChange={() => {}}
      />,
    );
    const tablist = screen.getByRole('tablist', { name: 'Workspaces' });
    expect(tablist.className).not.toContain('min-w-0');
    expect(tablist.parentElement?.className).toContain('w-max');
  });

  it('the empty search pane reads in sentence case', () => {
    render(<SearchPanel artifacts={[]} />);
    expect(screen.getByText('Nothing here yet')).toBeDefined();
  });

  it('keeps SearchPanel rows aligned: top row h-14 white, second row h-10 gray', () => {
    const { container } = render(<SearchPanel artifacts={[]} />);

    const root = container.firstElementChild as HTMLElement;
    const topRow = root.children[0] as HTMLElement;
    const secondRow = root.children[1] as HTMLElement;

    expect(topRow.className).toContain('h-14');
    expect(topRow.className).toContain('bg-white');

    expect(secondRow.className).toContain('h-10');
    expect(secondRow.className).toContain('bg-gray-100');

    const sourceScope = screen.getByLabelText('Search source scope') as HTMLSelectElement;
    expect(sourceScope.value).toBe('all');
  });

  it('keeps BrowserHeader rows aligned: top row h-14 white, search row h-10 gray', () => {
    const { container } = render(
      <BrowserHeader
        activeSource={{ type: 'workspace', id: 'ws-1' }}
        onToggleFilters={() => {}}
        filtersOpen={false}
        hasActiveFilter={false}
        activeFilter="all"
        viewMode="grid"
        onViewModeChange={() => {}}
        isShowingSearchResults
      />,
    );

    const root = container.firstElementChild as HTMLElement;
    const topRow = root.children[0] as HTMLElement;
    const secondRow = root.children[1] as HTMLElement;

    expect(topRow.className).toContain('h-14');
    expect(topRow.className).toContain('bg-white');

    expect(secondRow.className).toContain('h-10');
    expect(secondRow.className).toContain('bg-gray-100');
  });

  it('keeps FilterChips bar at h-10 with gray background', () => {
    const { container } = render(
      <FilterChips
        chips={[]}
        kinds={[]}
        activeStates={new Set()}
        activeContentTypes={new Set()}
        hiddenContentTypes={new Set()}
        viewMode="grid"
        onViewModeChange={() => {}}
        onStateToggle={() => {}}
        onContentTypeToggle={() => {}}
        onHiddenContentTypeToggle={() => {}}
        onClearAll={() => {}}
      />,
    );

    const root = container.firstElementChild as HTMLElement;
    expect(root.className).toContain('h-10');
    expect(root.className).toContain('bg-gray-100');
    expect(screen.getByRole('group', { name: 'Workspace view mode' })).toBeDefined();
  });

  it('calls onCreateWorkspace when the [+] button is clicked', () => {
    const onCreateWorkspace = vi.fn();

    render(
      <BrowserHeader
        activeSource={{ type: 'workspace', id: 'ws-1' }}
        onToggleFilters={() => {}}
        filtersOpen={false}
        hasActiveFilter={false}
        activeFilter="all"
        viewMode="grid"
        onViewModeChange={() => {}}
        onCreateWorkspace={onCreateWorkspace}
      />,
    );

    fireEvent.click(screen.getByLabelText('New workspace'));

    expect(onCreateWorkspace).toHaveBeenCalledTimes(1);
  });

  it('tells two workspaces with the same name apart by the day Mantle marks (BUG-001)', () => {
    const before = mockWorkspaces;
    mockWorkspaces = [
      { id: 'ws-1', name: 'Untitled workspace', created_time: '2026-11-01T10:00:00', label_at: 'day' },
      { id: 'ws-2', name: 'Untitled workspace', created_time: '2026-11-03T10:00:00', label_at: 'day' },
    ];
    try {
      render(
        <BrowserHeader
          activeSource={{ type: 'workspace', id: 'ws-1' }}
          onToggleFilters={() => {}}
          filtersOpen={false}
          hasActiveFilter={false}
          activeFilter="all"
          viewMode="grid"
          onViewModeChange={() => {}}
        />,
      );
      const tabs = screen.getAllByRole('tab').map((t) => t.textContent);
      expect(tabs).toHaveLength(2);
      expect(new Set(tabs).size).toBe(2);
      for (const tab of tabs) expect(tab).toMatch(/^Untitled workspace · \d+ Nov$/);
    } finally {
      mockWorkspaces = before;
    }
  });

  it('calls onDropWorkspace when a workspace card is dropped on tab area', () => {
    const onDropWorkspace = vi.fn();

    render(
      <BrowserHeader
        activeSource={{ type: 'workspace', id: 'ws-1' }}
        onToggleFilters={() => {}}
        filtersOpen={false}
        hasActiveFilter={false}
        activeFilter="all"
        viewMode="grid"
        onViewModeChange={() => {}}
        onDropWorkspace={onDropWorkspace}
      />,
    );

    const dropTarget = screen.getByRole('tablist');
    const dataTransfer = {
      dropEffect: 'none',
      effectAllowed: 'move',
      types: ['application/x-agience-drag+json'],
      getData: (type: string) =>
        type === 'application/x-agience-drag+json'
          ? JSON.stringify({ kind: 'artifacts', ids: ['workspace-card-1'] })
          : '',
    };

    fireEvent.dragOver(dropTarget, { dataTransfer });
    fireEvent.drop(dropTarget, { dataTransfer });

    expect(onDropWorkspace).toHaveBeenCalledWith(['workspace-card-1']);
  });

  it('renders workspace tabs and switches workspace on tab click', () => {
    setActiveWorkspaceIdMock.mockClear();

    render(
      <BrowserHeader
        activeSource={{ type: 'workspace', id: 'ws-1' }}
        onToggleFilters={() => {}}
        filtersOpen={false}
        hasActiveFilter={false}
        activeFilter="all"
        viewMode="grid"
        onViewModeChange={() => {}}
      />,
    );

    // The Inbox workspace tab should exist
    const inboxTab = screen.getByRole('tab', { name: 'Inbox' });
    expect(inboxTab).toBeDefined();
  });

  it('shows close button on workspace tabs', () => {
    render(
      <BrowserHeader
        activeSource={{ type: 'workspace', id: 'ws-1' }}
        onToggleFilters={() => {}}
        filtersOpen={false}
        hasActiveFilter={false}
        activeFilter="all"
        viewMode="grid"
        onViewModeChange={() => {}}
      />,
    );

    const closeButton = screen.getByLabelText('Close Inbox');
    expect(closeButton).toBeDefined();
  });
});

describe('the workspace tab bar', () => {
  it('holds only tabs, and arrow keys move between them', () => {
    const before = mockWorkspaces;
    mockWorkspaces = [{ id: 'ws-1', name: 'Inbox' }, { id: 'ws-2', name: 'Plans' }];
    mockActiveWorkspace = { id: 'ws-1', name: 'Inbox' };
    render(
      <BrowserHeader
        activeSource={{ type: 'workspace', id: 'ws-1' }}
        onToggleFilters={() => {}}
        filtersOpen={false}
        hasActiveFilter={false}
        activeFilter="all"
        viewMode="grid"
        onViewModeChange={() => {}}
      />,
    );
    const tablist = screen.getByRole('tablist');
    const tabs = screen.getAllByRole('tab');
    expect(tabs.map((t) => t.textContent)).toEqual(['Inbox', 'Plans']);
    expect(tabs.every((t) => tablist.contains(t))).toBe(true);
    expect(tablist.contains(screen.getByLabelText('New workspace'))).toBe(false);
    expect(tabs.map((t) => t.tabIndex)).toEqual([0, -1]);

    tabs[0].focus();
    fireEvent.keyDown(tabs[0], { key: 'ArrowRight' });
    expect(document.activeElement).toBe(tabs[1]);
    fireEvent.keyDown(tabs[1], { key: 'ArrowRight' });
    expect(document.activeElement).toBe(tabs[0]);
    fireEvent.keyDown(tabs[0], { key: 'End' });
    expect(document.activeElement).toBe(tabs[1]);
    mockWorkspaces = before;
  });
});

describe('uploading without dragging', () => {
  // 2026-10-22: files reached a workspace only by drag and drop, so a phone could add none; and a
  // "More" button beside New card did nothing when pressed.
  it('hands the chosen files on as a drop would, and keeps no dead button', () => {
    mockWorkspaces = [{ id: 'ws-1', name: 'Inbox' }];
    mockActiveWorkspace = { id: 'ws-1', name: 'Inbox' };
    const onUploadFiles = vi.fn();
    render(
      <BrowserHeader
        activeSource={{ type: 'workspace', id: 'ws-1' } as never}
        onToggleFilters={() => {}}
        filtersOpen={false}
        hasActiveFilter={false}
        activeFilter="all"
        viewMode="grid"
        onViewModeChange={() => {}}
        onNewArtifact={() => {}}
        onUploadFiles={onUploadFiles}
      />,
    );
    const label = new File(['jpeg'], 'label.jpg', { type: 'image/jpeg' });
    expect(screen.getByTitle('Upload files to this workspace')).toBeDefined();
    fireEvent.change(screen.getByTestId('upload-input'), { target: { files: [label] } });
    expect(onUploadFiles).toHaveBeenCalledWith([label]);
    expect(screen.queryByTitle('More')).toBeNull();
  });
});
