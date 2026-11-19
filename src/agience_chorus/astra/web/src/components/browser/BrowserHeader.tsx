import { useState, useEffect, useMemo, useRef, type KeyboardEvent } from 'react';
import { FiChevronDown, FiPlus, FiSave, FiUpload, FiX } from 'react-icons/fi';
import { FolderOpen } from 'lucide-react';
import type { ActiveSource } from '../../types/workspace';
import type { ViewChoices } from '../../api/collections';
import { saveView } from '../../api/savedViews';

import { useWorkspaces } from '../../hooks/useWorkspaces';
import { usePreferences } from '../../hooks/usePreferences';
import { useCompactWhenTight } from '../../hooks/useCompactWhenTight';
import { workspaceLabels } from '@/utils/workspaceLabels';
import { isAgienceDrag, getDroppedArtifactIds } from '@/dnd/agienceDrag';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { keyList, keyedIn, keyedNotIn, sortedBy, without, withoutKey } from '@/display-state/lists';

type ViewOption = 'grid' | 'list';

type BrowserHeaderProps = {
  activeSource: ActiveSource;
  /** The choices the open collection is viewed with; a saved view keeps them. */
  viewChoices?: ViewChoices;
  onToggleFilters: () => void;
  filtersOpen: boolean;
  hasActiveFilter: boolean;
  activeFilter: string;
  viewMode: ViewOption;
  onViewModeChange: (mode: ViewOption) => void;
  isShowingSearchResults?: boolean;
  sortMode?: 'relevance' | 'recency';
  onSortChange?: (mode: 'relevance' | 'recency') => void;
  onNewArtifact?: () => void;
  /** Files chosen with the Upload button, as a drop onto the workspace would bring them. */
  onUploadFiles?: (files: File[]) => void;
  onCreateWorkspace?: () => void;
  onDropWorkspace?: (draggedIds: string[]) => void;
  /** Artifacts dropped on one workspace's tab: into that workspace. */
  onDropOnTab?: (workspaceId: string, draggedIds: string[]) => void;
  /** Right-click on a tab: delete that workspace, after a confirmation. */
  onDeleteWorkspace?: (workspaceId: string) => void;
  onRenameWorkspace?: (id: string, name: string) => void;
};

export default function BrowserHeader({
  activeSource,
  viewChoices,
  isShowingSearchResults = false,
  onNewArtifact,
  onUploadFiles,
  onCreateWorkspace,
  onDropWorkspace,
  onDropOnTab,
  onDeleteWorkspace,
  onRenameWorkspace,
}: BrowserHeaderProps) {
  const { preferences, updatePreferences } = usePreferences();
  const [isDropActive, setIsDropActive] = useState(false);
  const { workspaces, activeWorkspace, setActiveWorkspaceId, openWorkspaceTab } = useWorkspaces();
  const [editingTabId, setEditingTabId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState('');
  const editInputRef = useRef<HTMLInputElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // The tabs keep their full width. When they do not fit, the buttons on the right drop their
  // labels first; only then does the tab strip scroll.
  const tabRoomRef = useRef<HTMLDivElement>(null);
  const tabContentRef = useRef<HTMLDivElement>(null);
  const actionsRef = useRef<HTMLDivElement>(null);
  const compactActions = useCompactWhenTight(tabRoomRef, tabContentRef, actionsRef);

  const canSaveView = !isShowingSearchResults && activeSource?.type === 'collection';

  const handleSaveView = async () => {
    if (!canSaveView) return;
    await saveView(activeSource.id, viewChoices ?? { apart: [], kinds: [], hidden_kinds: [], sort: '' },
      activeWorkspace?.id);
  };

  const browserPrefs = useMemo(
    () => ((preferences.browser as Record<string, unknown> | undefined) ?? {}),
    [preferences.browser]
  );

  const dockedTabIds = useMemo(() => {
    const raw = (browserPrefs as { dockedWorkspaceCardIds?: unknown }).dockedWorkspaceCardIds;
    return Array.isArray(raw) ? keyList(raw) : undefined;
  }, [browserPrefs]);

  const visibleWorkspaces = useMemo(
    () => (dockedTabIds ? keyedIn(workspaces, w => w.id, dockedTabIds) : workspaces),
    [workspaces, dockedTabIds]
  );

  const showDockHint = visibleWorkspaces.length === 0;
  // Every workspace the person reaches and has not docked, their own and those shared with them,
  // offered by name (BUG-016, 2026-11-10: with an empty tab bar there was no way to find one, since
  // search returns no workspace).
  // Same-name workspaces are told apart by the day they were made (BUG-001).
  const labels = useMemo(() => workspaceLabels(workspaces), [workspaces]);
  const undockedWorkspaces = useMemo(
    () => sortedBy(dockedTabIds ? keyedNotIn(workspaces, w => w.id, dockedTabIds) : [], w => String(w.name)),
    [workspaces, dockedTabIds]
  );

  const hasActiveWorkspace = activeSource?.type === 'workspace' && Boolean(activeWorkspace?.id);

  // When the tab strip scrolls, the open workspace's tab stays in view.
  const activeTabId = activeWorkspace?.id;
  useEffect(() => {
    if (!activeTabId) return;
    const tab = tabContentRef.current?.querySelector<HTMLElement>(`[data-testid="tab-${activeTabId}"]`);
    tab?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
  }, [activeTabId]);

  const handleTabClick = (id: string) => {
    if (activeWorkspace?.id === id && activeSource?.type !== 'workspace') {
      // Force re-derive activeSource when switching back from non-workspace view
      setActiveWorkspaceId(null);
      setTimeout(() => setActiveWorkspaceId(id), 0);
      return;
    }
    setActiveWorkspaceId(id);
  };

  const handleCloseTab = (workspaceId: string) => {
    const nextDocked = dockedTabIds
      ? without(dockedTabIds, workspaceId)
      : withoutKey(workspaces, w => w.id, workspaceId).map(w => w.id);

    void updatePreferences({
      browser: { ...browserPrefs, dockedWorkspaceCardIds: nextDocked },
    });

    if (activeWorkspace?.id === workspaceId) {
      const next = workspaces.find(
        (w) => w.id !== workspaceId && (dockedTabIds ? dockedTabIds.includes(w.id) : true),
      );
      setActiveWorkspaceId(next?.id ?? null);
    }
  };

  const handleStartRename = (workspaceId: string, currentName: string) => {
    setEditingTabId(workspaceId);
    setEditingName(currentName);
    setTimeout(() => editInputRef.current?.select(), 0);
  };

  const handleFinishRename = () => {
    if (editingTabId && editingName.trim()) {
      onRenameWorkspace?.(editingTabId, editingName.trim());
    }
    setEditingTabId(null);
    setEditingName('');
  };

  // Arrow keys, Home and End move between the workspace tabs; Tab leaves the bar.
  const moveTabFocus = (event: KeyboardEvent<HTMLDivElement>) => {
    const keys = ['ArrowLeft', 'ArrowRight', 'Home', 'End'];
    if (!keys.includes(event.key)) return;
    const tabs = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('[role="tab"]'));
    const at = tabs.indexOf(document.activeElement as HTMLElement);
    if (at < 0 || tabs.length === 0) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 0
      : event.key === 'End' ? tabs.length - 1
      : (at + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    tabs[next].focus();
  };

  return (
    <div className="bg-white">
      {/* Top row: workspace tabs + controls */}
      <div className="flex h-14 items-center justify-between border-b border-gray-200 bg-white px-2 sm:px-4">
        <div className="flex-1 flex items-center gap-2 min-w-0 overflow-hidden">
          <div
            ref={tabRoomRef}
            className={`flex items-center overflow-x-auto scrollbar-thin w-full ${isDropActive ? 'bg-sky-50/50 rounded' : ''}`}
            onDragOver={(event) => {
              if (!isAgienceDrag(event.dataTransfer)) {
                setIsDropActive(false);
                return;
              }
              event.preventDefault();
              event.dataTransfer.dropEffect = 'move';
              setIsDropActive(true);
            }}
            onDragLeave={(event) => {
              // Only deactivate when leaving the tab area entirely
              if (!(event.currentTarget as HTMLElement).contains(event.relatedTarget as Node)) {
                setIsDropActive(false);
              }
            }}
            onDrop={(event) => {
              setIsDropActive(false);
              if (!isAgienceDrag(event.dataTransfer)) return;
              const draggedIds = getDroppedArtifactIds(event.dataTransfer);
              if (!draggedIds.length) return;
              event.preventDefault();
              event.stopPropagation();
              onDropWorkspace?.(draggedIds);
            }}
          >
            {showDockHint && (
              <div
                className={`flex min-w-0 flex-1 items-center rounded-md border border-dashed px-4 py-2 text-sm transition-colors ${isDropActive ? 'border-sky-400 bg-sky-50 text-sky-800' : 'border-slate-300 bg-slate-50 text-slate-600'}`}
                aria-label="Dock a workspace here"
              >
                <span className="truncate">
                  {undockedWorkspaces.length ? 'Choose a workspace to dock.' : 'Find a workspace and dock it here.'}
                </span>
              </div>
            )}

            <div ref={tabContentRef} className="flex w-max items-center gap-1">
            {visibleWorkspaces.length > 0 && (
            <div role="tablist" aria-label="Workspaces" className="flex items-center gap-1" onKeyDown={moveTabFocus}>
            {visibleWorkspaces.map((workspace) => {
              const isActive = activeWorkspace?.id === workspace.id;
              const isEditing = editingTabId === workspace.id;
              return (
                <div
                  key={workspace.id}
                  className="group relative min-w-[7rem] max-w-[14rem]"
                  data-testid={`tab-${workspace.id}`}
                  onDragOver={(event) => {
                    if (!onDropOnTab || !isAgienceDrag(event.dataTransfer)) return;
                    event.preventDefault();
                    event.stopPropagation();
                    event.dataTransfer.dropEffect = 'move';
                    setIsDropActive(false);
                  }}
                  onDrop={(event) => {
                    if (!onDropOnTab || !isAgienceDrag(event.dataTransfer)) return;
                    const draggedIds = getDroppedArtifactIds(event.dataTransfer);
                    if (!draggedIds.length) return;
                    event.preventDefault();
                    event.stopPropagation();
                    setIsDropActive(false);
                    onDropOnTab(workspace.id, draggedIds);
                  }}
                >
                  {isEditing ? (
                    <input
                      ref={editInputRef}
                      value={editingName}
                      onChange={(e) => setEditingName(e.target.value)}
                      onBlur={handleFinishRename}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') handleFinishRename();
                        if (e.key === 'Escape') { setEditingTabId(null); setEditingName(''); }
                      }}
                      className="h-10 w-full pl-4 pr-10 rounded-sm border border-purple-400 text-sm font-medium bg-white focus:outline-none focus:ring-1 focus:ring-purple-400"
                      autoFocus
                    />
                  ) : (
                    <button
                      type="button"
                      role="tab"
                      data-workspace-id={workspace.id}
                      aria-selected={isActive}
                      tabIndex={isActive || (!activeWorkspace && workspace === visibleWorkspaces[0]) ? 0 : -1}
                      onClick={() => handleTabClick(workspace.id)}
                      onDoubleClick={() => handleStartRename(workspace.id, workspace.name)}
                      onContextMenu={(e) => {
                        if (!onDeleteWorkspace) return;
                        e.preventDefault();
                        onDeleteWorkspace(workspace.id);
                      }}
                      className={`h-10 w-full truncate pl-4 pr-10 rounded-sm border text-sm font-medium transition-none ${isActive ? 'bg-gradient-to-r from-purple-400/20 via-pink-400/20 to-blue-400/20 border-purple-300/40 text-purple-900' : 'bg-white/50 border-purple-200/30 text-gray-700 hover:bg-purple-50/30 hover:border-purple-300/40'}`}
                      title={`${labels.get(workspace.id) ?? workspace.name} (double-click to rename${onDeleteWorkspace ? ', right-click to delete' : ''})`}
                    >
                      {labels.get(workspace.id) ?? workspace.name}
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); handleCloseTab(workspace.id); }}
                    className="absolute right-1.5 top-1/2 -translate-y-1/2 w-5 h-5 inline-flex items-center justify-center rounded border border-gray-200 bg-white text-gray-500 transition-none hover:text-gray-700 hover:border-gray-300"
                    title="Close tab"
                    aria-label={`Close ${labels.get(workspace.id) ?? workspace.name}`}
                  >
                    <FiX className="w-3.5 h-3.5" />
                  </button>
                </div>
              );
            })}
            </div>
            )}

            {undockedWorkspaces.length > 0 && openWorkspaceTab && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    type="button"
                    className="flex-shrink-0 h-10 px-3 inline-flex items-center gap-1 rounded-sm border border-purple-200/30 bg-white/50 text-sm text-gray-700 hover:bg-purple-50/30"
                    title="Dock a workspace you can open"
                    aria-label="Dock a workspace"
                  >
                    Dock
                    <FiChevronDown className="w-4 h-4" />
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" className="max-h-80 w-64 overflow-auto">
                  {undockedWorkspaces.map((workspace) => (
                    <DropdownMenuItem
                      key={workspace.id}
                      onClick={() => openWorkspaceTab(workspace.id)}
                      className="cursor-pointer truncate"
                    >
                      {labels.get(workspace.id) ?? workspace.name}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            )}

            {/* [+] button: creates workspace on click */}
            <button
              type="button"
              onClick={() => onCreateWorkspace?.()}
              className={`flex-shrink-0 h-10 w-10 inline-flex items-center justify-center rounded-sm border border-dashed bg-white/50 text-gray-700 transition-colors ${isDropActive ? 'border-sky-400 bg-sky-50 text-sky-700' : 'border-purple-200/30 hover:bg-purple-50/30 hover:border-purple-300/40'}`}
              title="New workspace (or drop a workspace onto this tab bar)"
              aria-label="New workspace"
            >
              <FiPlus className="w-4 h-4" />
            </button>
            </div>
          </div>
        </div>

        <div ref={actionsRef} className="flex flex-shrink-0 items-center gap-2 ml-2 sm:ml-4">
          {/* New artifact in the open workspace. It carries a label so it never reads as the tab
              bar's dashed "+", which creates a workspace. */}
          {!isShowingSearchResults && hasActiveWorkspace && (
            <button
              onClick={onNewArtifact}
              className="h-10 px-3 inline-flex items-center gap-1.5 rounded bg-purple-600 text-white text-sm font-medium hover:bg-purple-700"
              title="New artifact in this workspace"
              aria-label="New artifact"
            >
              <FiPlus size={16} />
              <span className={compactActions ? 'hidden' : 'hidden sm:inline'}>New artifact</span>
            </button>
          )}

          {/* Upload: the same as dropping files on the workspace, for whoever cannot drag (a phone,
              a keyboard). On a phone the picker offers the camera. */}
          {!isShowingSearchResults && hasActiveWorkspace && onUploadFiles && (
            <>
              <button
                onClick={() => fileInputRef.current?.click()}
                className="h-10 px-3 inline-flex items-center gap-1.5 rounded border border-gray-300 text-sm font-medium hover:bg-accent"
                title="Upload files to this workspace"
                aria-label="Upload"
              >
                <FiUpload size={16} />
                <span className={compactActions ? 'hidden' : 'hidden sm:inline'}>Upload</span>
              </button>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                className="hidden"
                data-testid="upload-input"
                onChange={(e) => {
                  const files = Array.from(e.target.files ?? []);
                  e.target.value = '';
                  if (files.length) onUploadFiles(files);
                }}
              />
            </>
          )}

          {/* Save current collection view as View */}
          {canSaveView && (
            <button
              onClick={handleSaveView}
              className="h-10 w-10 inline-flex items-center justify-center rounded border border-teal-500 text-teal-700 hover:bg-teal-50"
              title="Save this collection view as a View artifact"
            >
              <FiSave size={16} />
            </button>
          )}

        </div>
      </div>

      {/* Bottom row: only rendered when showing search results label */}
      {isShowingSearchResults && (
        <div className="flex h-10 items-center justify-between border-b border-gray-200 bg-gray-100 px-4 text-[11px] text-muted-foreground">
          <div className="flex items-center gap-2 min-w-0">
            <FolderOpen size={14} className="text-purple-600" />
            <span className="font-medium text-purple-700 truncate">Search results</span>
          </div>
        </div>
      )}
    </div>
  );
}

