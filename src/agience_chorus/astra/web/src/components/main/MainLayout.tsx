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
import type { SearchResponse } from "../../api/types/search";
import type { Artifact } from "../../context/workspace/workspace.types";
import FloatingCardWindow from "../windows/FloatingCardWindow";
import { getContentType } from "@/registry/content-types";
import { resolveSearchHitsToArtifacts } from "../../utils/resolveSearchHits";

function MainLayout() {
  const [activeSource, setActiveSource] = useState<ActiveSource>(null);
  const [selectedArtifactId, setSelectedArtifactId] = useState<string | null>(null);
  const [searchSortMode, setSearchSortMode] = useState<'relevance' | 'recency'>('relevance');
  const [clearSearchTrigger, setClearSearchTrigger] = useState(0);
  // Resolved search result artifacts to display in SearchPanel
  const [resolvedSearchArtifacts, setResolvedSearchArtifacts] = useState<Artifact[]>([]);
  const [isResolvingSearch, setIsResolvingSearch] = useState(false);

  // Floating windows (opened artifacts)
  const [openArtifactWindowIds, setOpenArtifactWindowIds] = useState<string[]>([]);
  const [artifactWindowEditIds, setArtifactWindowEditIds] = useState<string[]>([]);

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
    addExistingArtifact,
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

  const openOrFocusArtifactWindow = useCallback((artifactId: string, options?: { startInEditMode?: boolean }) => {
    const id = `artifact:${artifactId}`;
    setOpenArtifactWindowIds((prev) => {
      if (prev.includes(id)) {
        return [...prev.filter((x) => x !== id), id];
      }
      return [...prev, id];
    });
    if (options?.startInEditMode) {
      setArtifactWindowEditIds((prev) => (prev.includes(id) ? prev : [...prev, id]));
    }
  }, []);

  // Closing a window only closes it. A created card is kept, typed into or not (John, 2026-10-31):
  // an empty new card closed at once was discarded, and read as a card that disappeared.
  const closeArtifactWindow = useCallback((windowId: string) => {
    setOpenArtifactWindowIds((prev) => prev.filter((id) => id !== windowId));
    setArtifactWindowEditIds((prev) => prev.filter((id) => id !== windowId));
  }, []);

  const focusArtifactWindow = useCallback((windowId: string) => {
    setOpenArtifactWindowIds((prev) => {
      if (!prev.includes(windowId)) return prev;
      return [...prev.filter((id) => id !== windowId), windowId];
    });
  }, []);

  const handleOpenArtifact = useCallback(
    (artifact: Artifact, options?: { startInEditMode?: boolean }) => {
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

  const openWindows = useMemo(() => {
    return openArtifactWindowIds
      .map((id) => ({
        id,
        artifactId: id.startsWith('artifact:') ? id.slice('artifact:'.length) : id,
      }))
      .filter((w) => Boolean(w.artifactId));
  }, [openArtifactWindowIds]);

  const handleOpenCollectionFromContainer = (collectionId: string) => {
    setActiveSource({ type: 'collection', id: collectionId });
    setSelectedArtifactId(null);
    unselectAllArtifacts();
  };

  // ── Search ──────────────────────────────────────────────────────────────────

  const handleSearchResults = useCallback(async (results: SearchResponse) => {
    if (!results.hits || results.hits.length === 0) {
      setResolvedSearchArtifacts([]);
      return;
    }
    setIsResolvingSearch(true);
    try {
      const artifacts = await resolveSearchHitsToArtifacts(results.hits);
      setResolvedSearchArtifacts(artifacts);
    } catch (err) {
      console.error('[MainLayout] Failed to resolve search hits:', err);
      setResolvedSearchArtifacts([]);
    } finally {
      setIsResolvingSearch(false);
    }
  }, []);

  const handleSearchClear = useCallback(() => {
    setResolvedSearchArtifacts([]);
  }, []);

  const handleAddToWorkspace = useCallback(
    (artifact: Artifact) => {
      addExistingArtifact(artifact);
    },
    [addExistingArtifact],
  );

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

  // A result that leaves the active workspace's list (removed, trashed) leaves the results. Only one
  // that was in the list: an archived result never is. 2026-10-29, a tester: restoring one of two
  // archived results took both off the list, because the restore refreshed the workspace's list and
  // the other, still archived, was not in it.
  const listedIdsRef = useRef<{ workspace: string | null; ids: Set<string> }>({ workspace: null, ids: new Set() });
  useEffect(() => {
    const ids = new Set(
      artifacts
        .flatMap((artifact) => [artifact.id, artifact.root_id])
        .filter((value): value is string => typeof value === 'string' && value.trim().length > 0)
        .map(String),
    );
    const before = listedIdsRef.current;
    listedIdsRef.current = { workspace: activeWorkspaceId ?? null, ids };
    if (!activeWorkspaceId || before.workspace !== activeWorkspaceId) return;
    const left = new Set([...before.ids].filter((id) => !ids.has(id)));
    if (!left.size) return;

    setResolvedSearchArtifacts((prev) => prev.filter((artifact) =>
      artifact.collection_id !== activeWorkspaceId
      || ![artifact.id, artifact.root_id].some((id) => id && left.has(String(id)))));
  }, [activeWorkspaceId, artifacts]);

  return (
    <div className="flex flex-col h-screen">
      {/* Command Palette (Cmd+K / Ctrl+K) */}
      <CommandPalette
        onWorkspaceSelect={(workspaceId) => {
          setActiveSource({ type: 'workspace', id: workspaceId });
          setResolvedSearchArtifacts([]);
          setClearSearchTrigger((prev) => prev + 1);
          setSelectedArtifactId(null);
          unselectAllArtifacts();
        }}
        onCollectionSelect={(collectionId) => {
          setActiveSource({ type: 'collection', id: collectionId });
          setResolvedSearchArtifacts([]);
          setClearSearchTrigger((prev) => prev + 1);
          setSelectedArtifactId(null);
          unselectAllArtifacts();
        }}
        onMcpServerSelect={(serverId) => {
          setActiveSource({ type: 'mcp-server', id: serverId });
          setResolvedSearchArtifacts([]);
          setClearSearchTrigger((prev) => prev + 1);
          setSelectedArtifactId(null);
          unselectAllArtifacts();
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
      />

      {/* Two-Panel Layout */}
      <div className="flex-1 overflow-hidden flex flex-col">
        <TwoPanelLayout
          leftPanel={
            <SearchPanel
              artifacts={resolvedSearchArtifacts}
              isLoading={isResolvingSearch}
              onResults={handleSearchResults}
              onClear={handleSearchClear}
              clearTrigger={clearSearchTrigger}
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