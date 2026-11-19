import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ARTIFACT_CHANGED_EVENT, changeOf } from '@/constants/strings';

import type { ActiveSource } from "../../types/workspace";
import FooterBar from "./MainFooter";
import { WorkspacePanel } from "../workspace/WorkspacePanel";
import HeaderBar from "./MainHeader";
import CommandPalette from "../command-palette/CommandPalette";
import { TwoPanelLayout } from "../layout/TwoPanelLayout";
import { SearchPanel } from "../search/SearchPanel";
import { useWorkspace } from "../../hooks/useWorkspace";
import { useWorkspaces } from "../../hooks/useWorkspaces";
import { useAddToWorkspace } from "@/hooks/useAddToWorkspace";
import type { SearchResponse } from "../../api/types/search";
import type { Artifact } from "../../context/workspace/workspace.types";
import FloatingCardWindow from "../windows/FloatingCardWindow";
import type { OpenArtifactOptions, WindowRect } from '@/utils/windowPlacement';
import { getContentType } from "@/registry/content-types";
import { onLinkedArtifact } from "../../utils/linkedArtifact";
import { useNarrowViewport } from "@/hooks/useNarrowViewport";
import { useShortcuts } from "@/context/shortcuts/useShortcuts";
import { present, toEnd, without } from '@/display-state/lists';

function MainLayout() {
  const [activeSource, setActiveSource] = useState<ActiveSource>(null);
  // Below 640 px one panel shows at a time; the top bar switches between them.
  const narrow = useNarrowViewport();
  const [phonePanel, setPhonePanel] = useState<'left' | 'right'>('right');
  const [selectedArtifactId, setSelectedArtifactId] = useState<string | null>(null);
  const [searchSortMode, setSearchSortMode] = useState<'relevance' | 'recency'>('relevance');
  const [clearSearchTrigger, setClearSearchTrigger] = useState(0);
  // Resolved search result artifacts to display in SearchPanel
  const [resolvedSearchArtifacts, setResolvedSearchArtifacts] = useState<Artifact[]>([]);

  // Floating windows (opened artifacts)
  const [openArtifactWindowIds, setOpenArtifactWindowIds] = useState<string[]>([]);
  const [artifactWindowEditIds, setArtifactWindowEditIds] = useState<string[]>([]);
  // The window each artifact window was opened from, where it was then; the new one opens beside it.
  const [artifactWindowOpeners, setArtifactWindowOpeners] = useState<Record<string, WindowRect>>({});

  // Settings modal state, driven from HeaderBar. There is no 'llm-keys' section: the platform
  // runs model-free, so there is nothing for an LLM Keys settings panel to hold.
  const [settingsInitialSection, setSettingsInitialSection] = useState<
    'profile' | 'billing' | undefined
  >(undefined);
  const [settingsScopedCollectionId, setSettingsScopedCollectionId] = useState<
    string | undefined
  >(undefined);

  // Get workspace context
  const {
    artifacts,
    keepOpenedArtifact,
    unselectAllArtifacts,
  } = useWorkspace();
  const { activeWorkspaceId } = useWorkspaces();

  // Panel widths for header coordination
  const [panelWidths, setPanelWidths] = useState<{ left: number; right: number }>({
    left: 340,
    right: 900,
  });
  const [isPanelResizing, setIsPanelResizing] = useState(false);

  const handlePanelWidthsChange = useCallback((widths: { left: number; right: number }) => {
    setPanelWidths((prev) => {
      const tol = 0.5;
      if (Math.abs(prev.left - widths.left) < tol && Math.abs(prev.right - widths.right) < tol) {
        return prev;
      }
      return widths;
    });
  }, []);

  const prevWorkspaceIdRef = useRef<string | null>(null);

  useEffect(() => {
    if (!activeWorkspaceId) {
      prevWorkspaceIdRef.current = null;
      return;
    }
    if (prevWorkspaceIdRef.current === activeWorkspaceId) return;
    prevWorkspaceIdRef.current = activeWorkspaceId;

    setActiveSource((prev) => {
      if (!prev || prev.type !== 'workspace' || prev.id !== activeWorkspaceId) {
        return { type: 'workspace', id: activeWorkspaceId };
      }
      return prev;
    });

    setSelectedArtifactId(null);
    unselectAllArtifacts();
    setOpenArtifactWindowIds([]);
  }, [activeWorkspaceId, unselectAllArtifacts]);

  const openOrFocusArtifactWindow = useCallback((artifactId: string, options?: OpenArtifactOptions) => {
    const id = `artifact:${artifactId}`;
    const from = options?.from;
    setOpenArtifactWindowIds((prev) => {
      if (prev.includes(id)) {
        return toEnd(prev, id);
      }
      if (from) setArtifactWindowOpeners((openers) => ({ ...openers, [id]: from }));
      return [...prev, id];
    });
    if (options?.startInEditMode) {
      setArtifactWindowEditIds((prev) => (prev.includes(id) ? prev : [...prev, id]));
    }
  }, []);

  // Closing a window only closes it. A created card is kept, typed into or not (John, 2026-10-31):
  // an empty new card closed at once was discarded, and read as a card that disappeared.
  const closeArtifactWindow = useCallback((windowId: string) => {
    setOpenArtifactWindowIds((prev) => without(prev, windowId));
    setArtifactWindowEditIds((prev) => without(prev, windowId));
    setArtifactWindowOpeners((prev) => {
      if (!(windowId in prev)) return prev;
      const next = { ...prev };
      delete next[windowId];
      return next;
    });
  }, []);

  const focusArtifactWindow = useCallback((windowId: string) => {
    setOpenArtifactWindowIds((prev) => {
      if (!prev.includes(windowId)) return prev;
      return toEnd(prev, windowId);
    });
  }, []);

  // Escape closes the window on top. An open menu or dialog takes Escape first (it marks the key
  // handled), and a field being typed in keeps it.
  const { registerShortcut } = useShortcuts();
  const topWindowId = openArtifactWindowIds[openArtifactWindowIds.length - 1];
  useEffect(() => {
    if (!topWindowId) return;
    return registerShortcut({
      id: 'windows:close-top',
      label: 'Close the top window',
      group: 'windows',
      groupTitle: 'Windows',
      combos: ['Escape'],
      handler: (event) => {
        event.preventDefault();
        closeArtifactWindow(topWindowId);
      },
    });
  }, [topWindowId, registerShortcut, closeArtifactWindow]);

  const handleOpenArtifact = useCallback(
    (artifact: Artifact, options?: OpenArtifactOptions) => {
      const contentType = getContentType(artifact);
      const artifactId = artifact.id ? String(artifact.id) : null;

      // Opened from outside the active workspace: kept as opened, which its window reads and every
      // edit patches, rather than in the center panel's list, which that panel replaces.
      if (artifactId && !artifacts.some((current) => String(current.id) === artifactId)) {
        keepOpenedArtifact(artifact);
      }

      if (
        ['tree', 'grid', 'list'].includes(contentType.defaultMode) &&
        !contentType.isContainer &&
        !options?.startInEditMode
      ) {
        return;
      }
      if (artifactId) openOrFocusArtifactWindow(artifactId, options);
    },
    [artifacts, keepOpenedArtifact, openOrFocusArtifactWindow],
  );

  // A link to one artifact that is not a workspace (FR-030) opens it in its own window, kept as
  // opened, as an artifact opened from outside the active workspace is.
  useEffect(() => onLinkedArtifact((artifact) => {
    if (!artifact.id) return;
    keepOpenedArtifact(artifact);
    openOrFocusArtifactWindow(String(artifact.id));
  }), [keepOpenedArtifact, openOrFocusArtifactWindow]);

  const openWindows = useMemo(() => {
    return present(openArtifactWindowIds.map((id) => {
      const artifactId = id.startsWith('artifact:') ? id.slice('artifact:'.length) : id;
      return artifactId && { id, artifactId };
    }));
  }, [openArtifactWindowIds]);

  const handleOpenCollectionFromContainer = (collectionId: string) => {
    setActiveSource({ type: 'collection', id: collectionId });
    setSelectedArtifactId(null);
    unselectAllArtifacts();
    setPhonePanel('right');
  };

  // ── Search ──────────────────────────────────────────────────────────────────

  const handleSearchResults = useCallback((results: SearchResponse) => {
    setResolvedSearchArtifacts(results.artifacts ?? []);
  }, []);

  const handleSearchClear = useCallback(() => {
    setResolvedSearchArtifacts([]);
  }, []);

  // BUG-075: the search panel's "Add to workspace" asks which workspace, as the centre's does.
  const { addToWorkspace: handleAddToWorkspace, picker: addToWorkspacePicker } = useAddToWorkspace();

  // A search result changed elsewhere shows the change. 2026-10-23, a tester restored a card opened
  // from archived results and its result kept the Archived badge.
  useEffect(() => {
    const onChange = (e: Event) => {
      const change = changeOf(e);
      if (!change) return;
      setResolvedSearchArtifacts((prev) => prev.map((a) =>
        String(a.id) === change.id || String(a.root_id) === change.id ? { ...a, ...change } as Artifact : a));
    };
    window.addEventListener(ARTIFACT_CHANGED_EVENT, onChange);
    return () => window.removeEventListener(ARTIFACT_CHANGED_EVENT, onChange);
  }, []);

  // When the active workspace's list changes, the open search asks again, so its results are
  // Mantle's answer for what the workspace holds now.
  const [refreshSearchTrigger, setRefreshSearchTrigger] = useState(0);
  const listedWorkspaceRef = useRef<string | null>(null);
  useEffect(() => {
    const before = listedWorkspaceRef.current;
    listedWorkspaceRef.current = activeWorkspaceId ?? null;
    if (activeWorkspaceId && before === activeWorkspaceId) setRefreshSearchTrigger((n) => n + 1);
  }, [activeWorkspaceId, artifacts]);

  return (
    <div className="flex flex-col h-screen w-full min-w-0 overflow-x-hidden">
      {addToWorkspacePicker}
      {/* Command Palette (Cmd+K / Ctrl+K) */}
      <CommandPalette
        onWorkspaceSelect={(workspaceId) => {
          setActiveSource({ type: 'workspace', id: workspaceId });
          setResolvedSearchArtifacts([]);
          setClearSearchTrigger((prev) => prev + 1);
          setSelectedArtifactId(null);
          unselectAllArtifacts();
          setPhonePanel('right');
        }}
        onCollectionSelect={(collectionId) => {
          setActiveSource({ type: 'collection', id: collectionId });
          setResolvedSearchArtifacts([]);
          setClearSearchTrigger((prev) => prev + 1);
          setSelectedArtifactId(null);
          unselectAllArtifacts();
          setPhonePanel('right');
        }}
        onMcpServerSelect={(serverId) => {
          setActiveSource({ type: 'mcp-server', id: serverId });
          setResolvedSearchArtifacts([]);
          setClearSearchTrigger((prev) => prev + 1);
          setSelectedArtifactId(null);
          unselectAllArtifacts();
          setPhonePanel('right');
        }}
      />

      {/* Global Header Bar */}
      <HeaderBar
        activeSource={activeSource}
        sidebarWidthPx={panelWidths.left}
        isPanelResizing={isPanelResizing}
        settingsInitialSection={settingsInitialSection}
        settingsScopedCollectionId={settingsScopedCollectionId}
        onSettingsSectionClear={() => {
          setSettingsInitialSection(undefined);
          setSettingsScopedCollectionId(undefined);
        }}
        onArtifactCreated={handleOpenArtifact}
        narrowPanel={narrow ? phonePanel : undefined}
        onNarrowPanelChange={setPhonePanel}
      />

      {/* Two-Panel Layout */}
      <div className="flex-1 overflow-hidden flex flex-col">
        <TwoPanelLayout
          leftPanel={
            <SearchPanel
              artifacts={resolvedSearchArtifacts}
              onResults={handleSearchResults}
              onClear={handleSearchClear}
              clearTrigger={clearSearchTrigger}
              refreshTrigger={refreshSearchTrigger}
              onAddToWorkspace={handleAddToWorkspace}
              onOpenArtifact={handleOpenArtifact}
              onCollectionSelect={handleOpenCollectionFromContainer}
              sortMode={searchSortMode}
              onSortChange={setSearchSortMode}
            />
          }
          rightPanel={
            <WorkspacePanel
              activeSource={activeSource}
              selectedArtifactId={selectedArtifactId}
              searchResultArtifacts={resolvedSearchArtifacts}
              onArtifactSelect={(artifactId) => {
                setSelectedArtifactId(artifactId ?? null);
              }}
              onOpenArtifact={handleOpenArtifact}
            />
          }
          onPanelWidthsChange={handlePanelWidthsChange}
          onResizingChange={setIsPanelResizing}
          singlePanel={narrow ? phonePanel : undefined}
        />

        {/* Floating artifact windows, in a layer of their own under every overlay (z-50: Settings,
            dialogs, menus): each window's z-index orders it among the windows only. 2026-10-29, a
            tester: an open card window covered the Settings modal. */}
        <div className="relative z-40" data-testid="artifact-window-layer">
        {openWindows.map((w, idx) => (
          <FloatingCardWindow
            key={w.id}
            artifactId={w.artifactId}
            zIndex={50 + idx}
            windowIndex={idx}
            initialViewState={artifactWindowEditIds.includes(w.id) ? 'edit' : undefined}
            openedFrom={artifactWindowOpeners[w.id]}
            onFocus={() => focusArtifactWindow(w.id)}
            onSnapToGrid={(x, y) => {
              console.log('Snap to grid at', x, y);
              closeArtifactWindow(w.id);
            }}
            onClose={() => closeArtifactWindow(w.id)}
            onOpenCollection={handleOpenCollectionFromContainer}
            onOpenArtifact={handleOpenArtifact}
          />
        ))}
        </div>
      </div>

      {/* Footer Bar — full width */}
      <FooterBar />
    </div>
  );
}

export default MainLayout;