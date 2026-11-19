/**
 * CommandPalette - Global search and navigation interface
 * 
 * Gmail-style command palette triggered by Cmd+K (Mac) or Ctrl+K (Windows/Linux).
 * Provides fuzzy search across workspaces, collections, and MCP servers with
 * recent items tracking.
 * 
 * Features:
 * - Keyboard shortcut (⌘K / Ctrl+K)
 * - Fuzzy search with cmdk
 * - Recent items (the person's recents, kept by Crystal)
 * - Keyboard navigation (↑↓ arrows, Enter)
 * - 5 groups: Recent, Workspaces, Collections, MCP Servers, Quick Actions
 * 
 * @example
 * ```tsx
 * <CommandPalette
 *   onWorkspaceSelect={(id) => setActiveWorkspace(id)}
 *   onCollectionSelect={(id) => openCollection(id)}
 *   onMcpServerSelect={(id) => openMcpServer(id)}
 * />
 * ```
 */

import { useEffect, useMemo, useState, useCallback } from 'react';
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from '@/components/ui/command';
import { NotebookPen, FolderOpen, Search, Wand2 } from 'lucide-react';
import McpIcon from '../icons/McpIcon';
import { useWorkspaces } from '../../hooks/useWorkspaces';
import { useWorkspace } from '../../hooks/useWorkspace';
import { CollectionResponse } from '../../api/types';
import { listCollections } from '../../api/collections';
import CollectionPlace from '@/components/common/CollectionPlace';
import { useShortcuts } from '@/context/shortcuts/useShortcuts';
import { workspaceLabels } from '@/utils/workspaceLabels';
import { listRecents, visitRecent, type RecentArtifact } from '../../api/recents';
import { COLLECTION_CONTENT_TYPE, WORKSPACE_CONTENT_TYPE } from '@/utils/content-type';
import { artifactTitle } from '@/utils/artifactContext';

interface CommandPaletteProps {
  /** Callback when a workspace is selected */
  onWorkspaceSelect?: (workspaceId: string) => void;
  /** Callback when a collection is selected */
  onCollectionSelect?: (collectionId: string) => void;
  /** Callback when an MCP server is selected */
  onMcpServerSelect?: (serverId: string) => void;
}

const RECENT_ICONS: Record<string, typeof NotebookPen> = {
  [WORKSPACE_CONTENT_TYPE]: NotebookPen,
  [COLLECTION_CONTENT_TYPE]: FolderOpen,
};

export default function CommandPalette({
  onWorkspaceSelect,
  onCollectionSelect,
  onMcpServerSelect,
}: CommandPaletteProps) {
  const [open, setOpen] = useState(false);
  const [collections, setCollections] = useState<CollectionResponse[]>([]);
  const [recentItems, setRecentItems] = useState<RecentArtifact[]>([]);
  const { workspaces, openWorkspaceTab } = useWorkspaces();
  // Same-name workspaces are told apart by the day they were made (BUG-001).
  const labels = useMemo(() => workspaceLabels(workspaces), [workspaces]);
  const { selectedArtifactIds, extractInformationFromSelection } = useWorkspace();
  const { registerShortcut } = useShortcuts();

  // Fixed list of MCP servers; not sourced from an API.
  const mcpServers = [
    { id: 'agience_core', name: 'Agience' }
  ];

  // Load collections
  useEffect(() => {
    listCollections()
      .then(setCollections)
      .catch(console.error);
  }, []);

  // The person's recents, as Crystal keeps them.
  useEffect(() => {
    if (!open) return;
    listRecents().then(setRecentItems).catch(console.error);
  }, [open]);

  const addRecentItem = useCallback((id: string) => {
    visitRecent(id).then(setRecentItems).catch(console.error);
  }, []);

  useEffect(() => {
    return registerShortcut({
      id: 'shortcuts:command-palette',
      label: 'Open command palette',
      group: 'Navigation',
      groupTitle: 'Navigation',
      groupOrder: 1,
      combos: ['mod+k'],
      handler: (event) => {
        event.preventDefault();
        setOpen((current) => !current);
      },
      options: {
        description: 'Search workspaces, collections, and quick actions',
        allowInInputs: true,
        order: 5,
      },
    });
  }, [registerShortcut]);

  // Handle workspace selection
  const handleWorkspaceSelect = useCallback((workspaceId: string) => {
    addRecentItem(workspaceId);
    // Opened as a tab: a workspace not yet docked would otherwise be selected and dropped again.
    openWorkspaceTab(workspaceId);
    onWorkspaceSelect?.(workspaceId);
    setOpen(false);
  }, [openWorkspaceTab, onWorkspaceSelect, addRecentItem]);

  // Handle collection selection
  const handleCollectionSelect = useCallback((collectionId: string) => {
    addRecentItem(collectionId);
    onCollectionSelect?.(collectionId);
    setOpen(false);
  }, [onCollectionSelect, addRecentItem]);

  // Handle MCP server selection
  const handleMcpServerSelect = useCallback((serverId: string) => {
    onMcpServerSelect?.(serverId);
    setOpen(false);
  }, [onMcpServerSelect]);

  return (
    <CommandDialog open={open} onOpenChange={setOpen}>
      <CommandInput placeholder="Search workspaces, collections, MCP servers..." />
      <CommandList>
        <CommandEmpty>No results found.</CommandEmpty>

        {/* Recent Items Group */}
        {recentItems.length > 0 && (
          <>
            <CommandGroup heading="Recent">
              {recentItems.map((item) => {
                const Icon = RECENT_ICONS[item.content_type ?? ''] ?? FolderOpen;
                const name = item.name || artifactTitle(item) || item.id;
                return (
                  <CommandItem
                    key={`recent-${item.id}`}
                    value={`recent-${name}-${item.id}`}
                    onSelect={() => {
                      if (item.content_type === WORKSPACE_CONTENT_TYPE) handleWorkspaceSelect(item.id);
                      else handleCollectionSelect(item.id);
                    }}
                    className="cursor-pointer"
                  >
                    <Icon className="mr-2 h-4 w-4 text-gray-500" />
                    <span className="font-medium text-sm truncate">{name}</span>
                  </CommandItem>
                );
              })}
            </CommandGroup>
            <CommandSeparator />
          </>
        )}

        {/* Workspaces Group */}
        {workspaces.length > 0 && (
          <>
            <CommandGroup heading="Workspaces">
              {workspaces.map((workspace) => (
                <CommandItem
                  key={workspace.id}
                  value={`workspace-${workspace.name}-${workspace.id}`}
                  onSelect={() => handleWorkspaceSelect(workspace.id)}
                  className="cursor-pointer"
                >
                  <NotebookPen className="mr-2 h-4 w-4 text-gray-500" />
                  <div className="flex flex-col flex-1 min-w-0">
                    <span className="font-medium text-sm truncate">{labels.get(workspace.id) ?? workspace.name}</span>
                    {workspace.description && (
                      <span className="text-xs text-gray-500 truncate">
                        {workspace.description}
                      </span>
                    )}
                  </div>
                </CommandItem>
              ))}
            </CommandGroup>
            <CommandSeparator />
          </>
        )}

        {/* Collections Group */}
        {collections.length > 0 && (
          <>
            <CommandGroup heading="Collections">
              {collections.map((collection) => (
                <CommandItem
                  key={collection.id}
                  value={`collection-${collection.name}-${collection.id}`}
                  onSelect={() => handleCollectionSelect(collection.id)}
                  className="cursor-pointer"
                >
                  <FolderOpen className="mr-2 h-4 w-4 text-gray-500" />
                  <div className="flex flex-col flex-1 min-w-0">
                    <span className="font-medium text-sm truncate">{collection.name}</span>
                    <CollectionPlace collection={collection} className="text-xs text-gray-600 truncate" />
                    {collection.description && (
                      <span className="text-xs text-gray-500 truncate">
                        {collection.description}
                      </span>
                    )}
                  </div>
                </CommandItem>
              ))}
            </CommandGroup>
            <CommandSeparator />
          </>
        )}

        {/* MCP Servers Group */}
        {mcpServers.length > 0 && (
          <CommandGroup heading="MCP Servers">
            {mcpServers.map((server) => (
              <CommandItem
                key={server.id}
                value={`mcp-${server.name}`}
                onSelect={() => handleMcpServerSelect(server.id)}
                className="cursor-pointer"
              >
                <McpIcon size={16} className="mr-2 text-gray-500" />
                <span className="font-medium text-sm">{server.name}</span>
              </CommandItem>
            ))}
          </CommandGroup>
        )}

        {/* Quick Actions Group */}
        <CommandSeparator />
        <CommandGroup heading="Quick Actions">
          <CommandItem
            value="extract-units"
            onSelect={() => {
              setOpen(false);
              void extractInformationFromSelection();
            }}
            className="cursor-pointer"
          >
            <Wand2 className="mr-2 h-4 w-4 text-gray-500" />
            <span className="text-sm">
              Extract information{selectedArtifactIds.length > 0 ? ` (${selectedArtifactIds.length} selected)` : ''}
            </span>
          </CommandItem>
          <CommandItem
            value="search-artifacts"
            onSelect={() => {
              // Closes the palette; does not run a search.
              setOpen(false);
            }}
            className="cursor-pointer"
          >
            <Search className="mr-2 h-4 w-4 text-gray-500" />
            <span className="text-sm">Search artifacts…</span>
          </CommandItem>
          <CommandItem
            value="create-workspace"
            onSelect={() => {
              // Closes the palette; does not create a workspace.
              setOpen(false);
            }}
            className="cursor-pointer"
          >
            <NotebookPen className="mr-2 h-4 w-4 text-gray-500" />
            <span className="text-sm">Create Workspace</span>
          </CommandItem>
          <CommandItem
            value="create-collection"
            onSelect={() => {
              // Closes the palette; does not create a collection.
              setOpen(false);
            }}
            className="cursor-pointer"
          >
            <FolderOpen className="mr-2 h-4 w-4 text-gray-500" />
            <span className="text-sm">Create Collection</span>
          </CommandItem>
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}
