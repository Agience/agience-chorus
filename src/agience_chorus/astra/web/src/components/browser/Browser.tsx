// "Browser" – center column artifact browser/workspace showing the Artifact Grid/List for the active source.
import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import { useWorkspace } from "../../hooks/useWorkspace";
import { useWorkspaces } from "../../hooks/useWorkspaces";
import { useCollections } from '../../context/collections/CollectionsContext';
import { usePreferences } from '../../hooks/usePreferences';
import { useAddressedValue } from "../../hooks/useAddressedView";
import CardList from "../common/CardList";
import CardGrid from "../common/CardGrid";
import ArtifactEditModal from "../common/CardDetailModal";
import FilterBar from "./FilterBar";
import FilterChips from "./FilterChips";
import EmptyState from "./EmptyState";
import MultiCardToolbar from "./MultiCardToolbar";
import { CollectionPicker } from '../modals/CollectionPicker';
import { BulkTagDialog, type BulkTagApplyRequest } from '../modals/BulkTagDialog';
import WorkspaceDetailModal from '../modals/WorkspaceDetailModal';
import { useAddToWorkspace } from '@/hooks/useAddToWorkspace';
import { Artifact } from "../../context/workspace/workspace.types";
import { ArtifactCreate, ArtifactUpdate } from "../../api/types";
import { addArtifactToWorkspace, importCollectionArtifactToWorkspace, initiateUpload, updateUploadStatus } from "../../api/workspaces";
import { addArtifactToCollection } from "../../api/collections";
import { uploadWithProgress, withUploadProgress } from "../../utils/upload";
import { mantleUrl } from "../../api/api";
import type { ActiveSource } from "../../types/workspace";
import { getCollectionArtifacts, runView, subscribeCollectionEvents, type ViewResult } from "../../api/collections";
import { useConfirm } from "@/context/dialog/useConfirm";
import { ARTIFACT_CHANGED_EVENT, CARD_CONFIRM, BULK_CONFIRM, BUTTON_LABELS, MEMBERSHIP_CHANGED_EVENT, SHORTCUTS, TRASH_RETENTION_DAYS, announceMembershipChange, changeOf, containerOf } from "@/constants/strings";
import { noun } from "@/product/copy";
import { inboxWorkspaceId as inboxWorkspaceIdOf } from "@/utils/inbox";
import { allows, type CardRemoveMode } from "@/utils/artifact-permissions";
import { useShortcuts } from "@/context/shortcuts/useShortcuts";
import BrowserHeader from "./BrowserHeader";
import { safeParseArtifactContext, stringifyArtifactContext } from '@/utils/artifactContext';
import { getContentTypeById } from '@/registry/content-types';
import CardTypePickerDialog from './CardTypePickerDialog';
import { WORKSPACE_CONTENT_TYPE } from '@/utils/content-type';
import { AGIENCE_DRAG_CONTENT_TYPE, getDroppedArtifactIds } from '@/dnd/agienceDrag';
import { toast } from 'sonner';
import { IncomingInvites } from './IncomingInvites';
import { errorDetail } from '../../utils/errorDetail';
import { announceRemoval } from '@/utils/removal';
import { removeWorkspaceArtifact } from '@/api/workspaces';
import { getArtifact } from '@/api/artifacts';
import { changeMemberships, removeArtifactFromCollection } from '@/api/collections';
import { useWindowInUse } from '@/hooks/useWindowInUse';
import { LockedActionsContext } from '@/context/view/useLockedActions';
import { keyList, keySet, keyedIn, notIn, present, removeFromSet, splitList, toggleInSet, unique, without, withoutKey } from '@/display-state/lists';

const INLINE_BYTES_MAX = 128 * 1024; // 128 KiB (~32K tokens, good chunk size for LLM processing)
const HIDDEN_CONTENT_TYPE_FILTERS_STORAGE_KEY = 'agience.browser.hiddenMimeCategories';
const STACKED_ARTIFACT_FAMILIES_STORAGE_KEY = 'agience.browser.stackArtifacts';

type ArtifactState = 'all' | 'archived';
type SortOption = 'recent' | 'title' | 'created' | 'modified' | 'manual';
type ViewOption = 'grid' | 'list';



interface BrowserProps {
  activeSource: ActiveSource;
  /** Currently selected artifact ID for preview pane */
  selectedArtifactId?: string | null;
  /** Resolved artifacts currently visible in the search panel. */
  searchResultArtifacts?: Artifact[];
  /** Callback when an artifact is selected */
  onArtifactSelect?: (artifactId: string | null) => void;
  /** Callback when an artifact should be opened (e.g., floating window) */
  onOpenArtifact?: (artifact: Artifact, options?: { startInEditMode?: boolean }) => void;
  /** Sort mode for search results */
  searchSortMode?: 'relevance' | 'recency';
  /** Callback when sort mode changes */
  onSearchSortChange?: (mode: 'relevance' | 'recency') => void;
}



export default function Browser({ 
  activeSource, 
  selectedArtifactId, 
  searchResultArtifacts = [],
  onArtifactSelect,
  onOpenArtifact,
  searchSortMode = 'relevance',
  onSearchSortChange,
}: BrowserProps) {
  // selectedArtifactId is accepted for interface parity but not read here; void it to satisfy the unused-variable lint rule.
  void selectedArtifactId;
  const {
    artifacts,
    displayedArtifacts = [],
    selectedArtifactIds,
    removeArtifact,
    deleteArtifact,
    announceTrashed,
    selectArtifact,
    selectAllArtifacts,
    unselectAllArtifacts,
    addArtifact,
    addExistingArtifact,
    patchArtifactLocally,
    createArtifact,
    updateArtifact,
    registerNewArtifactHandler,
    moveArtifacts,
    importArtifactsByRootIds,
  } = useWorkspace();
  // setDisplayedArtifacts is exposed by WorkspaceProvider; some context implementations may not define it.
  const { setDisplayedArtifacts } = useWorkspace();
  const { preferences, updatePreferences } = usePreferences();
  const dangerConfirm = useConfirm();


  const latestArtifactsRef = useRef(artifacts);
  useEffect(() => { latestArtifactsRef.current = artifacts; }, [artifacts]);

  const { workspaces, activeWorkspace, createWorkspace, setActiveWorkspaceId, updateWorkspace, deleteWorkspace, restoreWorkspace, openWorkspaceTab } = useWorkspaces();
  const { collections } = useCollections();
  // The person's Inbox: their oldest own workspace, as Mantle provisions it. Not their user id.
  const inboxWorkspaceId = useMemo(() => inboxWorkspaceIdOf(workspaces), [workspaces]);
  // Use activeWorkspace ID, or fall back to inboxWorkspaceId if viewing a workspace, or empty string
  const workspaceId = activeWorkspace?.id || (activeSource?.type === 'workspace' ? inboxWorkspaceId : "") || "";
  const [editArtifact, setEditArtifact] = useState<ArtifactCreate | ArtifactUpdate | null>(null);
  const [isArtifactTypePickerOpen, setIsArtifactTypePickerOpen] = useState(false);
  const [sourceArtifacts, setSourceArtifacts] = useState<Artifact[]>([]); // For collection/MCP artifacts

  // Load artifacts based on activeSource
  useEffect(() => {
    if (!activeSource) {
      setSourceArtifacts([]);
      return;
    }

    if (activeSource.type === 'workspace') {
      // Use workspace artifacts from context
      setSourceArtifacts(artifacts);
    } else if (activeSource.type === 'collection') {
      // Load collection artifacts
      getCollectionArtifacts(activeSource.id)
        .then((collectionArtifacts) => {
          setSourceArtifacts(collectionArtifacts as Artifact[]);
        })
        .catch((error) => {
          console.error('Failed to load collection artifacts:', error);
          setSourceArtifacts([]);
        });
    } else if (activeSource.type === 'mcp-server') {
      // MCP-server sources have no artifacts list.
      setSourceArtifacts([]);
    }
  }, [activeSource, artifacts]);

  // Subscribe to real-time collection change events via SSE
  useEffect(() => {
    if (!activeSource || activeSource.type !== 'collection') return;
    const collectionId = activeSource.id;

    const unsubscribe = subscribeCollectionEvents(collectionId, {
      onArtifactCreated: (artifact) => {
        setSourceArtifacts(prev => {
          const key = String((artifact as Artifact).root_id ?? artifact.id);
          if (prev.some(c => String(c.root_id ?? c.id) === key)) return prev;
          return [...prev, artifact as Artifact];
        });
      },
      onArtifactUpdated: (artifact) => {
        setSourceArtifacts(prev =>
          prev.map(c => {
            const cKey = String(c.root_id ?? c.id);
            const aKey = String((artifact as Artifact).root_id ?? artifact.id);
            return cKey === aKey ? { ...c, ...artifact } as Artifact : c;
          })
        );
      },
      onArtifactDeleted: (artifactId) => {
        setSourceArtifacts(prev => withoutKey(prev, c => c.root_id ?? c.id, artifactId));
      },
      onCollectionRefreshed: () => {
        getCollectionArtifacts(collectionId)
          .then(arts => setSourceArtifacts(arts as Artifact[]))
          .catch(err => console.error('Failed to reload collection artifacts:', err));
      },
    });

    return unsubscribe;
  }, [activeSource]);

  // Filter/Sort/View state
  const [activeFilter, setActiveFilter] = useState<ArtifactState>('all');
  const [sortBy, setSortBy] = useState<SortOption>('recent');
  // The list layout has its own address (`?layout=list`), so Back returns to the grid.
  const [viewMode, setViewMode] = useAddressedValue<ViewOption>('layout', 'grid');
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [showBulkCollectionPicker, setShowBulkCollectionPicker] = useState(false);
  // The artifacts the picker assigns: one card's (right-click "Assign to collections…") or, when
  // null, the selection (the toolbar). One picker for both, so the two cannot drift apart.
  const [assignIds, setAssignIds] = useState<string[] | null>(null);
  const [showBulkTagDialog, setShowBulkTagDialog] = useState(false);
  const [stackArtifactFamilies, setStackArtifactFamilies] = useState<boolean>(() => {
    try {
      const raw = localStorage.getItem(STACKED_ARTIFACT_FAMILIES_STORAGE_KEY);
      return raw ? raw === 'true' : true;
    } catch {
      return true;
    }
  });
  const [collapsedArtifactSections, setCollapsedArtifactSections] = useState<Record<string, boolean>>({
    transcripts: true,
    'stream-sessions': true,
    'palette-outputs': true,
  });

  // Workspaces are primarily manually ordered via drag-reorder.
  // Default to manual sort when viewing a workspace so reorder doesn't appear to "snap back".
  useEffect(() => {
    const sourceType = activeSource?.type;
    if (!sourceType) return;

    if (sourceType === 'workspace') {
      setSortBy((prev) => (prev === 'manual' ? prev : 'manual'));
    } else {
      setSortBy((prev) => (prev === 'recent' ? prev : 'recent'));
    }
  }, [activeSource?.type]);
  
  // Publish the currently-displayed artifacts to workspace context so preview can render non-workspace artifacts
  useEffect(() => {
    if (typeof setDisplayedArtifacts === 'function') setDisplayedArtifacts(sourceArtifacts);
  }, [sourceArtifacts, setDisplayedArtifacts]);
  
  // Register keyboard shortcuts for artifact selection
  const { registerShortcut } = useShortcuts();
  
  useEffect(() => {
    // Only register shortcuts for workspace views (not collections or search results)
    if (activeSource?.type !== 'workspace') return;

    const cleanups: (() => void)[] = [];

    // Select all artifacts
    cleanups.push(registerShortcut({
      id: 'workspace:select-all',
      label: SHORTCUTS.SELECT_ALL.LABEL,
      group: 'Workspace',
      combos: ['mod+a'],
      handler: (e) => {
        e.preventDefault();
        selectAllArtifacts();
      },
      options: {
        description: SHORTCUTS.SELECT_ALL.DESCRIPTION
      }
    }));

    // Clear selection
    cleanups.push(registerShortcut({
      id: 'workspace:clear-selection',
      label: SHORTCUTS.CLEAR_SELECTION.LABEL,
      group: 'Workspace',
      combos: ['escape'],
      handler: (e) => {
        // Only clear if artifacts are selected
        if (selectedArtifactIds.length > 0) {
          e.preventDefault();
          unselectAllArtifacts();
        }
      },
      options: {
        description: SHORTCUTS.CLEAR_SELECTION.DESCRIPTION
      }
    }));

    return () => {
      cleanups.forEach(cleanup => cleanup());
    };
  }, [activeSource?.type, registerShortcut, selectAllArtifacts, selectedArtifactIds.length, unselectAllArtifacts]);
  
  // Additional filter chips state
  const [activeStateFilters, setActiveStateFilters] = useState(() => keySet<string>());
  const [activeContentTypeFilters, setActiveContentTypeFilters] = useState(() => keySet<string>());
  const [hiddenContentTypeFilters, setHiddenContentTypeFilters] = useState<Set<string>>(() => {
    try {
      const raw = localStorage.getItem(HIDDEN_CONTENT_TYPE_FILTERS_STORAGE_KEY);
      return keySet(raw ? keyList(JSON.parse(raw)) : []);
    } catch {
      return keySet<string>();
    }
  });

  useEffect(() => {
    localStorage.setItem(HIDDEN_CONTENT_TYPE_FILTERS_STORAGE_KEY, JSON.stringify(Array.from(hiddenContentTypeFilters)));
  }, [hiddenContentTypeFilters]);

  useEffect(() => {
    localStorage.setItem(STACKED_ARTIFACT_FAMILIES_STORAGE_KEY, String(stackArtifactFamilies));
  }, [stackArtifactFamilies]);
  
  const bulkSelectedArtifacts = useMemo(
    () => keyedIn(artifacts, (artifact) => artifact.id, selectedArtifactIds),
    [artifacts, selectedArtifactIds]
  );

  // The open container's view: Crystal runs the rules its members' types declare (what the
  // Archived and Closed chips set apart, each member's kind, the sorts) on the person's choices,
  // and the grid shows what comes back. Search results and server tools show as they arrive.
  const viewContainerId =
    activeSource?.type === 'collection' ? activeSource.id
      : activeSource?.type === 'workspace' ? workspaceId
        : '';
  const [view, setView] = useState<ViewResult | null>(null);
  const viewChoices = useMemo(() => ({
    apart: activeFilter === 'archived' && !activeStateFilters.has('archived')
      ? [...activeStateFilters, 'archived'] : [...activeStateFilters],
    kinds: [...activeContentTypeFilters],
    hidden_kinds: [...hiddenContentTypeFilters],
    sort: sortBy,
  }), [activeFilter, activeStateFilters, activeContentTypeFilters, hiddenContentTypeFilters, sortBy]);
  const viewRun = useRef(0);
  const reloadView = useCallback(() => {
    const run = ++viewRun.current;
    if (!viewContainerId) { setView(null); return; }
    runView(viewContainerId, viewChoices)
      .then(v => { if (run === viewRun.current) setView(v); })
      .catch(err => { console.error('Failed to run the view:', err); if (run === viewRun.current) setView(null); });
  }, [viewContainerId, viewChoices]);
  // Again on each change to the held members (a save, an archive, a new artifact) and whenever
  // Mantle reports a membership or an artifact changing, a moment after the last of a burst.
  useEffect(() => {
    const t = setTimeout(reloadView, 120);
    return () => clearTimeout(t);
  }, [reloadView, sourceArtifacts]);
  useEffect(() => {
    if (!viewContainerId) return;
    const onMembership = (e: Event) => { if (containerOf(e) === viewContainerId) reloadView(); };
    const onChange = (e: Event) => { if (changeOf(e)) reloadView(); };
    window.addEventListener(MEMBERSHIP_CHANGED_EVENT, onMembership);
    window.addEventListener(ARTIFACT_CHANGED_EVENT, onChange);
    return () => {
      window.removeEventListener(MEMBERSHIP_CHANGED_EVENT, onMembership);
      window.removeEventListener(ARTIFACT_CHANGED_EVENT, onChange);
    };
  }, [viewContainerId, reloadView]);

  const counts = useMemo(() => ({
    total: sourceArtifacts.length,
    archived: view?.chips.find(c => c.key === 'archived')?.count ?? 0,
  }), [sourceArtifacts.length, view]);

  // The view's members in its order, each as the workspace holds it now when it holds it.
  const viewed = useMemo(() => {
    const byKey = new Map<string, Artifact>();
    for (const a of view?.artifacts ?? []) byKey.set(String(a.root_id ?? a.id), a as Artifact);
    for (const c of sourceArtifacts) {
      const key = String(c.root_id ?? c.id);
      if (byKey.has(key)) byKey.set(key, c);
    }
    return byKey;
  }, [view, sourceArtifacts]);
  const filteredArtifacts = useMemo(() => {
    if (!viewContainerId) return sourceArtifacts;
    return [...viewed.values()];
  }, [viewContainerId, viewed, sourceArtifacts]);

  // The main list and the sections of produced members, as the view gathers them.
  const stackedArtifacts = useMemo(() => {
    if (!viewContainerId || !view) return { primaryArtifacts: filteredArtifacts, sections: [] as ArtifactSection[] };
    const pick = (keys: string[]) => keys.flatMap(k => viewed.get(k) ?? []);
    return {
      primaryArtifacts: pick(view.primary ?? []),
      sections: (view.sections ?? []).map((s): ArtifactSection => ({ id: s.id, title: s.title, artifacts: pick(s.keys) })),
    };
  }, [viewContainerId, view, viewed, filteredArtifacts]);
  const artifactCountsByOwnerId = useMemo(() => view?.owned ?? {}, [view]);
  const lockedActions = useMemo(() => view?.locked ?? {}, [view]);
  const shouldUseArtifactStacks =
    stackArtifactFamilies &&
    activeSource?.type === 'workspace' &&
    stackedArtifacts.sections.length > 0;
  // The bar acts on the workspace grid's selection, so it stands aside while the person works in a
  // window over the grid: BUG-019, 2026-11-10, a right-click in a collection window showed
  // "1 selected" for the collection selected in the grid behind it, and "Assign to Collections"
  // nested the collection instead of the card clicked.
  const windowInUse = useWindowInUse();
  const showFloatingToolbar = activeSource?.type === 'workspace' && bulkSelectedArtifacts.length > 0 && !windowInUse;
  const bulkCanDelete = useMemo(
    () => bulkSelectedArtifacts.some(a => allows(a, 'delete')),
    [bulkSelectedArtifacts]
  );
  const bulkHasLive = useMemo(
    () => bulkSelectedArtifacts.some(a => a.state !== 'archived'),
    [bulkSelectedArtifacts]
  );

  // Handlers for filter chips
  const handleStateFilterToggle = useCallback((state: string) => {
    setActiveStateFilters(prev => toggleInSet(prev, state));
  }, []);
  
  const handleContentTypeFilterToggle = useCallback((contentType: string) => {
    setActiveContentTypeFilters(prev => toggleInSet(prev, contentType));
  }, []);

  const handleHiddenContentTypeToggle = useCallback((contentType: string) => {
    setHiddenContentTypeFilters(prev => toggleInSet(prev, contentType));
    setActiveContentTypeFilters(prev => (prev.has(contentType) ? removeFromSet(prev, contentType) : prev));
  }, []);

  const handleClearAllFilters = useCallback(() => {
    setActiveStateFilters(keySet<string>());
    setActiveContentTypeFilters(keySet<string>());
    setHiddenContentTypeFilters(keySet<string>());
  }, []);

  // Any chip or drawer filter narrowing the view (search text is tracked separately).
  const isAnyFilterActive =
    activeFilter !== 'all' ||
    activeStateFilters.size > 0 ||
    activeContentTypeFilters.size > 0 ||
    hiddenContentTypeFilters.size > 0;
  // True when there are cards here and the filters hide all of them; an empty workspace
  // keeps its own empty state even while a (possibly remembered) filter is set.
  const filtersHideEverything = useMemo(() => {
    if (!isAnyFilterActive) return false;
    return sourceArtifacts.some((c: Artifact) => {
      if (activeSource?.type !== 'workspace' || !workspaceId) return true;
      return String(c.id ?? '') !== workspaceId && String(c.root_id ?? '') !== workspaceId;
    });
  }, [activeSource?.type, isAnyFilterActive, sourceArtifacts, workspaceId]);
  const handleClearEveryFilter = useCallback(() => {
    handleClearAllFilters();
    setActiveFilter('all');
  }, [handleClearAllFilters]);

  const toggleArtifactSection = useCallback((sectionId: string) => {
    setCollapsedArtifactSections((prev) => ({
      ...prev,
      [sectionId]: !(prev[sectionId] ?? true),
    }));
  }, []);

  const handleBulkMove = useCallback(() => {
    setAssignIds(null);
    setShowBulkCollectionPicker(true);
  }, []);
  const openAssignFor = useCallback((artifact: Artifact) => {
    if (!artifact.id) return;
    setAssignIds([String(artifact.id)]);
    setShowBulkCollectionPicker(true);
  }, []);

  // Add artifacts (by version/root id) into a collection with user feedback.
  // A 403/404 from the add endpoint means the caller lacks `create` on the
  // target — e.g. a read-only platform collection — so we surface a permission
  // error instead of failing silently. Returns the number actually added.
  const addArtifactsToCollectionWithFeedback = useCallback(async (
    collectionId: string,
    artifactIds: string[],
  ): Promise<number> => {
    let added = 0;
    let denied = false;
    let failed = false;
    for (const artifactId of artifactIds) {
      try {
        await addArtifactToCollection(collectionId, artifactId);
        added += 1;
      } catch (err) {
        const status = (err as { response?: { status?: number } })?.response?.status;
        if (status === 403 || status === 404) denied = true;
        else failed = true;
      }
    }
    if (denied) {
      toast.error("You don't have permission to add to this collection");
    } else if (failed && added === 0) {
      toast.error('Could not add to this collection');
    } else if (added > 0) {
      toast.success(`Added ${added} item${added === 1 ? '' : 's'} to collection`);
    }
    if (added > 0) announceMembershipChange({ container_id: collectionId });
    return added;
  }, []);

  // Where the selection is held, as Mantle reads it: containers holding all of it are ticked,
  // those holding some show as mixed (BUG-042: workspaces included). The picker opens on it.
  const [assignHeld, setAssignHeld] = useState<{ all: string[]; some: string[] } | null>(null);
  useEffect(() => {
    setAssignHeld(null);
    if (!showBulkCollectionPicker) return;
    const ids = assignIds ?? selectedArtifactIds;
    let live = true;
    changeMemberships(ids)
      .then(m => { if (live) setAssignHeld({ all: m.all, some: m.some }); })
      .catch(() => { if (live) setAssignHeld({ all: [], some: [] }); });
    return () => { live = false; };
  }, [showBulkCollectionPicker, assignIds, selectedArtifactIds]);

  const handleBulkSelectCollections = useCallback(async (collectionIds: string[], clearedPartialIds: string[] = []) => {
    const ids = assignIds ?? selectedArtifactIds;
    try {
      const { items, failed } = await changeMemberships(ids, { held: collectionIds, cleared: clearedPartialIds });
      if (failed.length) toast.error('Could not change every collection', { description: failed[0].detail });
      // Show what Mantle now says holds each one, rather than at the next refresh.
      for (const now of items) {
        const held = { committed_collection_ids: now.committed_collection_ids, container_ids: now.container_ids,
          containers: now.containers };
        for (const c of artifacts) {
          if (String(c.root_id ?? c.id) === now.root_id) patchArtifactLocally({ id: String(c.id), ...held });
        }
        setSourceArtifacts(prev => prev.map(c => (String(c.root_id ?? c.id) === now.root_id ? { ...c, ...held } : c)));
      }
      // Every container the picker showed or changed lists its members again.
      for (const container_id of unique([...collectionIds, ...clearedPartialIds, ...(assignHeld?.all ?? []), ...(assignHeld?.some ?? [])])) {
        announceMembershipChange({ container_id });
      }
    } catch (err) {
      toast.error('Could not change every collection', { description: errorDetail(err, 'Some changes were not saved') });
    }
    setShowBulkCollectionPicker(false);
    if (!assignIds) unselectAllArtifacts();
    setAssignIds(null);
  }, [assignIds, selectedArtifactIds, unselectAllArtifacts, patchArtifactLocally, artifacts, assignHeld]);

  const handleBulkAddTags = useCallback(async () => {
    setShowBulkTagDialog(true);
  }, []);

  const handleBulkApplyTags = useCallback(async ({ tags, replaceExisting }: BulkTagApplyRequest) => {
    for (const artifact of bulkSelectedArtifacts) {
      const id = String(artifact.id);
      // Read the artifact as stored, merge the tags, and write the whole list.
      try {
        const context = safeParseArtifactContext((await getArtifact(id)).context);
        const held = !replaceExisting && Array.isArray(context.tags) ? context.tags : [];
        await updateArtifact({ id, context: stringifyArtifactContext({ ...context, tags: unique([...held, ...tags]) }) });
      } catch (err) {
        toast.error('Could not add the tags', { description: errorDetail(err, 'The tags were not saved') });
        return;
      }
    }
  }, [bulkSelectedArtifacts, updateArtifact]);

  const browserPrefs = useMemo(
    () => ((preferences.browser as Record<string, unknown> | undefined) ?? {}),
    [preferences.browser]
  );

  const dockedWorkspaceTabIdsPref = useMemo(() => {
    const raw = (browserPrefs as { dockedWorkspaceCardIds?: unknown }).dockedWorkspaceCardIds;
    return Array.isArray(raw) ? keyList(raw) : undefined;
  }, [browserPrefs]);

  // If the artifact is a workspace card that points to a docked workspace tab, undock that workspace.
  const undockWorkspaceIfNeeded = useCallback((artifact: Artifact) => {
    const ctx = safeParseArtifactContext(artifact.context);
    if (ctx.content_type !== WORKSPACE_CONTENT_TYPE) return;
    const wsId = typeof ctx.workspace_id === 'string' ? ctx.workspace_id : undefined;
    if (!wsId || (dockedWorkspaceTabIdsPref && !dockedWorkspaceTabIdsPref.includes(wsId))) return;
    if (!workspaces.some(w => w.id === wsId)) return;

    const nextDocked = dockedWorkspaceTabIdsPref
      ? without(dockedWorkspaceTabIdsPref, wsId)
      : withoutKey(workspaces, w => w.id, wsId).map(w => w.id);

    void updatePreferences({ browser: { ...browserPrefs, dockedWorkspaceCardIds: nextDocked } });
  }, [browserPrefs, dockedWorkspaceTabIdsPref, updatePreferences, workspaces]);

  // Every bulk action sends the whole selection; Mantle decides each artifact. Archiving an
  // archived one or restoring a live one changes nothing, and a delete Mantle refuses comes back
  // with its reason.
  const handleBulkArchive = useCallback(async () => {
    const items = bulkSelectedArtifacts;
    if (items.length === 0) return;

    for (const artifact of items) {
      undockWorkspaceIfNeeded(artifact);
      await updateArtifact({ id: String(artifact.id), state: 'archived' });
    }
    unselectAllArtifacts();
  }, [bulkSelectedArtifacts, unselectAllArtifacts, updateArtifact, undockWorkspaceIfNeeded]);

  // Restore the archived part of the selection. The toolbar and a card's menu share it (2026-10-31,
  // a tester: the archived view's toolbar had no Restore, though the menu's did).
  const handleBulkRestore = useCallback(async () => {
    const items = bulkSelectedArtifacts;
    if (items.length === 0) return;
    for (const artifact of items) {
      await updateArtifact({ id: String(artifact.id), state: 'live' });
    }
    reloadView();
    unselectAllArtifacts();
  }, [bulkSelectedArtifacts, reloadView, unselectAllArtifacts, updateArtifact]);

  // Remove the selection from the container on screen, the way a single card's Remove does. It
  // called the workspace store's remove, which unlinks from the active workspace even while a
  // collection is on screen. `handleBrowserRemove` is declared further down, so it is reached
  // through a ref.
  const browserRemoveRef = useRef<((artifact: Artifact) => Promise<void>) | null>(null);
  const handleBulkDrop = useCallback(async () => {
    const items = bulkSelectedArtifacts;
    if (items.length === 0) return;
    for (const artifact of items) {
      await browserRemoveRef.current?.(artifact);
    }
    unselectAllArtifacts();
  }, [bulkSelectedArtifacts, unselectAllArtifacts]);

  const handleBulkDelete = useCallback(async () => {
    const items = bulkSelectedArtifacts;
    const count = items.length;
    if (count === 0) return;
    const confirmed = await dangerConfirm.confirm({
      title: BULK_CONFIRM.DELETE_TITLE(count),
      description: BULK_CONFIRM.DELETE_DESCRIPTION(count),
      confirmLabel: BULK_CONFIRM.DELETE_CONFIRM,
      cancelLabel: BUTTON_LABELS.CANCEL
    });

    if (!confirmed) return;

    const trashed: string[] = [];
    for (const artifact of items) {
      if (await deleteArtifact(String(artifact.id), { announce: false })) {
        trashed.push(String(artifact.id));
        undockWorkspaceIfNeeded(artifact);
      }
    }
    if (trashed.length) announceTrashed(trashed, `${trashed.length} ${noun(trashed.length).toLowerCase()}`);
    unselectAllArtifacts();
  }, [dangerConfirm, bulkSelectedArtifacts, deleteArtifact, announceTrashed, unselectAllArtifacts, undockWorkspaceIfNeeded]);

  // A menu opened on a card inside a selection of several acts on the whole selection, as the
  // toolbar does; on any other card, on that card alone. 2026-10-29, a tester: with three cards
  // selected, Trash from one card's menu moved only that card, and nothing said so.
  const handleSelectionAction = useCallback((actionId: string, artifact: Artifact): boolean => {
    if (selectedArtifactIds.length < 2 || !selectedArtifactIds.includes(String(artifact.id))) return false;
    switch (actionId) {
      case 'delete': void handleBulkDelete(); return true;
      case 'remove': void handleBulkDrop(); return true;
      case 'archive': void handleBulkArchive(); return true;
      case 'assign-collections': handleBulkMove(); return true;
      case 'restore': void handleBulkRestore(); return true;
      default: return false;
    }
  }, [selectedArtifactIds, handleBulkDelete, handleBulkDrop, handleBulkArchive, handleBulkMove, handleBulkRestore]);

  // Entire-workspace dropzone state
  const [, setDragDepth] = useState(0);
  const [, setWorkspaceDragKind] = useState<'file' | 'artifacts' | null>(null);
  const depthRef = useRef(0);

  const isFileDrag = (dt: DataTransfer | null | undefined) =>
    !!dt?.types?.includes("Files") || !!dt?.types?.includes("public.file-url");

  // Accept artifact drags on workspace background (append to end)
  const isArtifactsDrag = (dt: DataTransfer | null | undefined) => {
    if (!dt?.types) return false;
    const types = Array.from(dt.types);
    return (
      types.includes(AGIENCE_DRAG_CONTENT_TYPE) ||
      types.includes("application/json") ||
      types.includes("text/plain")
    );
  };

  const resetWorkspaceDragState = useCallback(() => {
    depthRef.current = 0;
    setDragDepth(0);
    setWorkspaceDragKind(null);
  }, []);

  useEffect(() => {
    window.addEventListener('dragend', resetWorkspaceDragState);
    window.addEventListener('drop', resetWorkspaceDragState);
    return () => {
      window.removeEventListener('dragend', resetWorkspaceDragState);
      window.removeEventListener('drop', resetWorkspaceDragState);
    };
  }, [resetWorkspaceDragState]);

  const isInlineText = (file: File) => {
    if (file.size > INLINE_BYTES_MAX) return false;
    const t = (file.type || "").toLowerCase();
    if (t.startsWith("text/")) return true;
    return ["application/json", "application/xml", "application/x-yaml", "application/javascript", "text/markdown"].includes(t);
  };

  useEffect(() => {
    const unsubscribe = registerNewArtifactHandler((artifact: ArtifactCreate | ArtifactUpdate) => {
      setEditArtifact(artifact);
    });
    return unsubscribe;
  }, [registerNewArtifactHandler]);

  const handleSave = async (artifact: ArtifactCreate | ArtifactUpdate) => {
    if ("id" in artifact && artifact.id) {
      await updateArtifact(artifact as ArtifactUpdate & { id: string });
    } else {
      await addArtifact(artifact as ArtifactCreate);
    }
    setEditArtifact(null);
  };

  const handleClose = () => setEditArtifact(null);

  const handleOpenTypePicker = useCallback(() => {
    if (activeSource?.type !== 'workspace') return;
    setIsArtifactTypePickerOpen(true);
  }, [activeSource?.type]);

  // [+] creates a new workspace (the backend indexes its container artifact for search),
  // then switches to the new workspace. No card is dropped into the current workspace.
  // A failed create is already toasted by WorkspacesProvider.createWorkspace.
  // One create at a time (BUG-058, 2026-11-10: a second click while the first was on its way made
  // a second workspace).
  // [+] asks for the name first; one left blank is named by Mantle, numbered against the
  // person's other workspaces.
  const creatingWorkspace = useRef(false);
  // The prompt's starting name, '' while it is open; null while it is closed.
  const [offeredWorkspaceName, setOfferedWorkspaceName] = useState<string | null>(null);
  const newWorkspaceInitial = useMemo(
    () => ({ name: offeredWorkspaceName ?? '', description: '' }),
    [offeredWorkspaceName],
  );
  const handleCreateWorkspace = useCallback(() => setOfferedWorkspaceName(''), []);
  const createNamedWorkspace = useCallback(async (name: string, description: string) => {
    if (creatingWorkspace.current) return;
    creatingWorkspace.current = true;
    try {
      const ws = await createWorkspace(name.trim(), description.trim(),
        { activate: false }).catch(() => null);
      if (!ws) return;
      setOfferedWorkspaceName(null);
      setActiveWorkspaceId(ws.id);
    } finally {
      creatingWorkspace.current = false;
    }
  }, [createWorkspace, setActiveWorkspaceId]);

  // BUG-075: "Add to workspace" asks which workspace and links the artifact there.
  const { addToWorkspace, picker: addToWorkspacePicker } = useAddToWorkspace();

  // "New artifact" from the no-source empty state: dock the Inbox (its id is the user id),
  // make it active, and open the type picker. The created card lands in the Inbox.
  const canCreateCardInInbox = Boolean(inboxWorkspaceId && workspaces.some(w => w.id === inboxWorkspaceId));
  const handleCreateCardInInbox = useCallback(() => {
    if (!inboxWorkspaceId || !workspaces.some(w => w.id === inboxWorkspaceId)) return;
    if (dockedWorkspaceTabIdsPref && !dockedWorkspaceTabIdsPref.includes(inboxWorkspaceId)) {
      void updatePreferences({
        browser: { ...browserPrefs, dockedWorkspaceCardIds: [...dockedWorkspaceTabIdsPref, inboxWorkspaceId] },
      });
    }
    setActiveWorkspaceId(inboxWorkspaceId);
    setIsArtifactTypePickerOpen(true);
  }, [browserPrefs, dockedWorkspaceTabIdsPref, inboxWorkspaceId, setActiveWorkspaceId, updatePreferences, workspaces]);

  // Double-click tab to rename workspace. Also updates the workspace container
  // artifact so the new name is reflected in search results.
  const handleRenameWorkspace = useCallback(async (id: string, name: string) => {
    await updateWorkspace({ id, name });
  }, [updateWorkspace]);

  // ---------------------------------------------------------------------------
  // Resolve dropped search-result IDs against known artifact pools.
  // Returns classified buckets so callers can route each artifact correctly.
  // ---------------------------------------------------------------------------
  type ResolvedDrop = {
    /** Collection-backed artifacts importable by root_id */
    collectionImports: string[];
    /** Workspace-native artifacts that need to be copied (content + context) */
    workspaceCopies: Artifact[];
    /** IDs already present in the active workspace (skip / reorder only) */
    alreadyPresent: string[];
    /** IDs not found in any known artifact pool — treated as collection root_ids */
    unresolved: string[];
  };

  const resolveDroppedIds = useCallback((draggedIds: string[]): ResolvedDrop => {
    const pool = [...searchResultArtifacts, ...artifacts, ...sourceArtifacts];
    const activeWsId = activeWorkspace?.id;

    const result: ResolvedDrop = {
      collectionImports: [],
      workspaceCopies: [],
      alreadyPresent: [],
      unresolved: [],
    };

    for (const id of draggedIds) {
      // Find the artifact in any available pool (search results, workspace, source)
      const artifact = pool.find(
        a => String(a.id ?? '') === id || String(a.root_id ?? '') === id,
      );

      if (!artifact) {
        // Not found in any pool — assume it's a collection root_id from a non-search drop
        result.unresolved.push(id);
        continue;
      }

      // Already in the active workspace?
      if (artifact.collection_id && artifact.collection_id === activeWsId) {
        result.alreadyPresent.push(id);
        continue;
      }

      // Has a root_id we can import from?
      const rootId = artifact.root_id ? String(artifact.root_id).trim() : '';
      if (rootId) {
        result.collectionImports.push(rootId);
        continue;
      }

      // Artifact without root_id — copy it
      if (artifact.collection_id) {
        result.workspaceCopies.push(artifact);
        continue;
      }

      // No root_id and no collection_id — treat as unresolved
      result.unresolved.push(id);
    }

    return result;
  }, [activeWorkspace?.id, artifacts, searchResultArtifacts, sourceArtifacts]);

  // ---------------------------------------------------------------------------
  // Unified drop handler: resolves IDs first, then dispatches import or copy.
  // ---------------------------------------------------------------------------
  const handleResolvedDrop = useCallback(async (
    draggedIds: string[],
    insertIndex: number,
    dragPayload?: {
      rootIds?: string[];
      versionIds?: string[];
      sourceType?: string;
      workspaceId?: string;
    },
  ) => {
    if (activeSource?.type === 'collection') {
      const targetCollectionId = activeSource.id;
      if (!targetCollectionId) return;

      let idsToAdd: string[];
      if (dragPayload?.sourceType === 'workspace' || dragPayload?.workspaceId) {
        idsToAdd = draggedIds.map(String);
      } else {
        const versionIds = keyList(dragPayload?.versionIds);
        const fallbackVersionIds = keyList(draggedIds.map((id) => [...searchResultArtifacts, ...artifacts, ...sourceArtifacts]
          .find((candidate) => String(candidate.id ?? '') === id || String(candidate.root_id ?? '') === id)?.id));
        idsToAdd = unique([...versionIds, ...fallbackVersionIds]);
      }
      idsToAdd = notIn(keyList(idsToAdd), [targetCollectionId]);

      // Surfaces a permission error if the target is read-only (e.g. a platform
      // collection) rather than silently doing nothing.
      const added = await addArtifactsToCollectionWithFeedback(targetCollectionId, idsToAdd);

      if (added > 0) {
        const refreshed = await getCollectionArtifacts(targetCollectionId);
        setSourceArtifacts(refreshed as Artifact[]);
      }
      return;
    }

    // Prevent dropping a workspace onto itself (container cannot contain itself)
    const filteredDraggedIds = notIn(draggedIds, present([activeWorkspace?.id]));
    if (filteredDraggedIds.length === 0) {
      // All dropped artifacts were self-drops; nothing to do
      return;
    }

    const { collectionImports, workspaceCopies, unresolved } = resolveDroppedIds(filteredDraggedIds);

    // 1. Collection imports — combine classified root_ids, unresolved IDs, and any root_ids from the drag payload
    const importIds = unique([...collectionImports, ...unresolved, ...keyList(dragPayload?.rootIds)]);
    if (importIds.length > 0) {
      importArtifactsByRootIds(importIds, insertIndex);
    }

    // 2. Workspace-native copies — create new artifacts with same content + context
    if (workspaceCopies.length > 0) {
      let offset = importIds.length;
      for (const src of workspaceCopies) {
        await createArtifact(
          { content: src.content ?? '', context: src.context ?? '' },
          insertIndex + offset,
        );
        offset += 1;
      }
    }
  }, [activeSource, activeWorkspace, artifacts, addArtifactsToCollectionWithFeedback, createArtifact, importArtifactsByRootIds, resolveDroppedIds, searchResultArtifacts, sourceArtifacts]);

  const createWorkspaceFromDroppedArtifacts = useCallback(async (draggedIds: string[]) => {
    // Prevent dropping a workspace onto itself (container cannot contain itself)
    const filteredDraggedIds = notIn(draggedIds, present([activeWorkspace?.id]));
    if (filteredDraggedIds.length === 0) {
      // All dropped artifacts were self-drops; nothing to do
      return false;
    }

    const { collectionImports, workspaceCopies, unresolved } = resolveDroppedIds(filteredDraggedIds);
    const importIds = [...collectionImports, ...unresolved];
    if (importIds.length === 0 && workspaceCopies.length === 0) return false;

    // A failed create is already toasted by WorkspacesProvider.createWorkspace.
    const ws = await createWorkspace('', '', { activate: false }).catch(() => null);
    if (!ws) return false;

    for (const rootId of importIds) {
      try {
        await importCollectionArtifactToWorkspace(ws.id, rootId);
      } catch {
        // Ignore unreadable or already-imported artifacts.
      }
    }

    for (const src of workspaceCopies) {
      try {
        await addArtifactToWorkspace(ws.id, {
          content: src.content ?? '',
          context: typeof src.context === 'string' ? src.context : stringifyArtifactContext(src.context ?? {}),
        });
      } catch {
        // Ignore copy failures so one bad artifact doesn't block the workspace creation.
      }
    }

    setActiveWorkspaceId(ws.id);
    return true;
  }, [activeWorkspace, createWorkspace, resolveDroppedIds, setActiveWorkspaceId]);

  // Drop a workspace card on the header: check workspace_id from context or use the
  // artifact's root_id directly. If no matching workspace, create one on the fly.
  const handleDropWorkspace = useCallback(async (draggedIds: string[]) => {
    // Prevent dropping a workspace onto itself (container cannot contain itself)
    const filteredDraggedIds = notIn(draggedIds, present([activeWorkspace?.id]));
    if (filteredDraggedIds.length === 0) {
      // All dropped artifacts were self-drops; nothing to do
      return;
    }

    const allArtifacts = [...searchResultArtifacts, ...artifacts, ...displayedArtifacts, ...sourceArtifacts];

    for (const id of filteredDraggedIds) {
      if (workspaces.some(w => String(w.id) === String(id))) {
        if (dockedWorkspaceTabIdsPref) {
          const nextDocked = dockedWorkspaceTabIdsPref.includes(id)
            ? dockedWorkspaceTabIdsPref
            : [...dockedWorkspaceTabIdsPref, id];
          if (nextDocked.length !== dockedWorkspaceTabIdsPref.length) {
            void updatePreferences({ browser: { ...browserPrefs, dockedWorkspaceCardIds: nextDocked } });
          }
        }
        setActiveWorkspaceId(id);
        return;
      }

      const artifact = allArtifacts.find(a => String(a.id ?? '') === id || String(a.root_id ?? '') === id);
      if (!artifact) continue;
      const ctx = safeParseArtifactContext(artifact.context);
      if (ctx.content_type !== WORKSPACE_CONTENT_TYPE) continue;

      const wsId =
        (typeof ctx.workspace_id === 'string' ? ctx.workspace_id : undefined) ??
        workspaces.find(w =>
          String(w.id) === String(artifact.id ?? '') ||
          String(w.id) === String(artifact.root_id ?? '') ||
          String(w.id) === String(artifact.collection_id ?? '')
        )?.id;

      if (wsId && workspaces.some(w => String(w.id) === wsId)) {
        if (dockedWorkspaceTabIdsPref) {
          const nextDocked = dockedWorkspaceTabIdsPref.includes(wsId)
            ? dockedWorkspaceTabIdsPref
            : [...dockedWorkspaceTabIdsPref, wsId];
          if (nextDocked.length !== dockedWorkspaceTabIdsPref.length) {
            void updatePreferences({ browser: { ...browserPrefs, dockedWorkspaceCardIds: nextDocked } });
          }
        }
        setActiveWorkspaceId(wsId);
        return;
      }

      const title = typeof ctx.title === 'string' ? ctx.title.trim() : '';
      const ws = await createWorkspace(title, '').catch(() => null);
      if (!ws) return;
      if (artifact.id) {
        void updateArtifact({
          id: String(artifact.id),
          context: stringifyArtifactContext({ ...ctx, workspace_id: ws.id }),
        });
      }
      setActiveWorkspaceId(ws.id);
      return;
    }

    const { collectionImports, workspaceCopies, unresolved } = resolveDroppedIds(draggedIds);
    const hasItemsToImport = [...collectionImports, ...unresolved, ...workspaceCopies].length > 0;
    if (hasItemsToImport) {
      await createWorkspaceFromDroppedArtifacts(draggedIds);
    }
  }, [activeWorkspace, artifacts, browserPrefs, createWorkspace, createWorkspaceFromDroppedArtifacts, displayedArtifacts, dockedWorkspaceTabIdsPref, resolveDroppedIds, searchResultArtifacts, setActiveWorkspaceId, sourceArtifacts, updateArtifact, updatePreferences, workspaces]);

  // A workspace is deleted from its tab (BUG-039, 2026-11-10: no control anywhere deleted one, so
  // stray "Untitled Workspace"s could not be removed). What it holds is detached, not destroyed
  // (`DELETE /artifacts/{id}` without `cascade`), and the Inbox is never offered.
  const handleDeleteWorkspace = useCallback(async (id: string) => {
    const ws = workspaces.find(w => String(w.id) === String(id));
    if (!ws) return;
    if (String(id) === String(inboxWorkspaceId)) {
      toast.error('The Inbox cannot be deleted');
      return;
    }
    const confirmed = await dangerConfirm.confirm({
      title: `Delete the workspace "${ws.name}"?`,
      description: 'The workspace goes for everyone it is shared with, and moves to your Trash with '
        + `what it holds. Restore it from Trash within ${TRASH_RETENTION_DAYS} days.`,
      confirmLabel: 'Delete workspace',
      cancelLabel: BUTTON_LABELS.CANCEL,
      tone: 'danger',
    });
    if (!confirmed) return;
    try {
      await deleteWorkspace(String(id));
      if (dockedWorkspaceTabIdsPref?.includes(String(id))) {
        void updatePreferences({ browser: { ...browserPrefs,
          dockedWorkspaceCardIds: without(dockedWorkspaceTabIdsPref, String(id)) } });
      }
      const name = ws.name;
      toast.success(`Moved "${name}" to Trash`, {
        action: {
          label: 'Undo',
          onClick: () => {
            restoreWorkspace(String(id))
              .then(() => openWorkspaceTab(String(id)))
              .catch((err) => toast.error('Could not restore the workspace', {
                description: errorDetail(err, '') || undefined,
              }));
          },
        },
      });
    } catch (err) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      toast.error(status === 403 ? 'Only someone who may delete this workspace can delete it'
        : 'Could not delete the workspace', { description: errorDetail(err, '') || undefined });
    }
  }, [browserPrefs, dangerConfirm, deleteWorkspace, dockedWorkspaceTabIdsPref, inboxWorkspaceId, openWorkspaceTab, restoreWorkspace, updatePreferences, workspaces]);

  // Artifacts dropped on a workspace's tab go into that workspace, and out of the open one when they
  // came from it (BUG-018, 2026-11-10: a drop on a tab fell through to the tab bar, which made a new
  // workspace of them, so the card seemed moved and the workspace named never held it). A workspace
  // card dropped on a tab is docked as before.
  const handleDropOnTab = useCallback(async (targetId: string, draggedIds: string[]) => {
    const ids = notIn(draggedIds, [targetId, ...workspaces.map(w => String(w.id))]);
    if (ids.length === 0) {
      await handleDropWorkspace(draggedIds);
      return;
    }
    const added = await addArtifactsToCollectionWithFeedback(targetId, ids);
    const fromOpen = activeSource?.type === 'workspace' && activeWorkspace?.id && activeWorkspace.id !== targetId;
    if (added !== ids.length || !fromOpen) return;
    for (const id of ids) {
      const card = artifacts.find(a => String(a.id ?? '') === id || String(a.root_id ?? '') === id);
      if (card) await removeArtifact(String(card.root_id ?? card.id));
    }
  }, [activeSource?.type, activeWorkspace?.id, addArtifactsToCollectionWithFeedback, artifacts, handleDropWorkspace, removeArtifact, workspaces]);

  const handleSelectArtifactType = useCallback(async (contentType: string) => {
    const type = getContentTypeById(contentType);
    setIsArtifactTypePickerOpen(false);
    // Sent untitled: Mantle names it after its type, numbered against the others beside it.
    const created = await createArtifact({ content_type: contentType, content: '' });
    if (!created) return;
    const startInEditMode = Boolean(type?.states.includes('edit'));
    onOpenArtifact?.(created, startInEditMode ? { startInEditMode: true } : undefined);
  }, [createArtifact, onOpenArtifact]);

  // Upload files: inline text stored directly, binary files uploaded to S3
  const uploadFilesAt = useCallback(async (files: File[], insertIndex: number) => {
    if (!workspaceId || !files.length) return;
    
    const newArtifactIds: string[] = [];
    
    // Phase 1: Initiate all uploads and create all artifacts immediately (shows all artifacts at once)
    const uploadTasks: Array<{
      file: File;
      artifactId: string;
      mode: 'inline' | 'put';
      url?: string;
    }> = [];
    
    for (let i = 0; i < files.length; i++) {
      const file = files[i];

      // Small text files: store content directly in artifact (no S3)
      if (isInlineText(file)) {
        const text = await file.text();
        const inlineCtx = {
                filename: file.name,
                mime: file.type || "text/plain",
                content_type: file.type || "text/plain",
                size: file.size,
                processing: { strategy: "deterministic", status: "ready" },
              };
        // Typed as the file, like an upload Mantle stores (`initiate_upload`): the type is what it
        // renders as and what a `type:` filter matches. 2026-10-23, a tester: an uploaded Markdown
        // file showed as a generic card and `type:text/markdown` did not find it.
        const created: Artifact | ArtifactCreate | null = await (createArtifact
          ? createArtifact({
              context: JSON.stringify(inlineCtx),
              content: text,
              content_type: inlineCtx.content_type,
            }, insertIndex + i)
          : (async () => {
              await addArtifact({
                context: JSON.stringify(inlineCtx),
                content: text
              });
              return null;
            })());
        const artifactId = String((created && 'id' in created ? created.id : undefined) ?? latestArtifactsRef.current[latestArtifactsRef.current.length - 1]?.id);
        if (artifactId) {
          newArtifactIds.push(artifactId);
          uploadTasks.push({ file, artifactId, mode: 'inline' });
        }
      } else {
        // Large or binary files: upload to S3, backend creates artifact
        // Mantle places it just before the member at the target index.
        const targetIndex = insertIndex + i;
        const beforeId = latestArtifactsRef.current[targetIndex]?.id;

        const init = await initiateUpload(workspaceId, {
          filename: file.name,
          content_type: file.type || "application/octet-stream",
          size: file.size,
          ...(beforeId ? { before_id: String(beforeId) } : {}),
        });
        const artifactId = init.upload_id;
        newArtifactIds.push(artifactId);

        // Add the artifact to local state immediately so it appears during upload
        addExistingArtifact(init.artifact as unknown as Artifact);

        // Queue upload task for phase 2
        // ⛔ `proxied` IS THE ONLY MODE THE PLATFORM RETURNS, AND THIS BRANCH USED TO REJECT IT.
        // `workspace_service.initiate_upload` sets it unconditionally — Mantle envelope-encrypts
        // on the byte path, so no presigned-URL mode exists to branch to. Against `"put"` and
        // `"multipart"` every upload fell to the throw below and the user was told to contact
        // support. Measured against a live node 2026-09-13.
        //
        // ⚠ `init.url` IS RELATIVE TO MANTLE (`/artifacts/{id}/content`). Handed to XHR unresolved
        // it addresses this app's own origin, where the SPA fallback answers 200 — an upload that
        // reports success and stores nothing.
        if (init.mode === "proxied" && init.url) {
          uploadTasks.push({ file, artifactId, mode: 'put', url: mantleUrl(init.url) });
        } else {
          throw new Error(
            `Unexpected upload mode: ${init.mode}. Please contact support.`
          );
        }
      }
    }
    
    // Phase 2: Process uploads sequentially (artifacts already visible)
    for (const task of uploadTasks) {
      if (task.mode === 'inline') {
        // Already completed in phase 1
        continue;
      }

      try {
        if (task.mode === 'put' && task.url) {
          // Single PUT for files <= 100MB. `uploadWithProgress` reports progress to the server
          // through PATCH /artifacts/{id}/upload-status; the bar here is updated in local state
          // only, because `upload` is store-owned and a context PATCH carrying it is ignored.
          await uploadWithProgress(workspaceId, task.artifactId, task.url, task.file, (progress) => {
            const ctx = latestArtifactsRef.current.find(c => c.id === task.artifactId)?.context;
            const next = withUploadProgress(ctx, progress);
            if (next) patchArtifactLocally({ id: task.artifactId, context: next });
          });

          // Notify backend that upload is complete; its answer is the finished artifact.
          const completedArtifact = await updateUploadStatus(workspaceId, task.artifactId, { status: "complete" });
          patchArtifactLocally(completedArtifact);
        }
      } catch (err) {
        const filename = task.file.name;
        toast.error(`Upload failed: ${filename}`, {
          description: err instanceof Error ? err.message : 'Unknown error',
        });
        // Mark upload as failed on backend
        try {
          await updateUploadStatus(workspaceId, task.artifactId, { status: "failed" });
        } catch { /* best-effort */ }
      }
    }
    
    // No need to refresh - artifacts were added to local state during initiation
    // and updated during upload progress and completion
    
    // Mantle placed each artifact where it was dropped
    // No need to reorder after upload
  }, [workspaceId, createArtifact, addArtifact, addExistingArtifact, patchArtifactLocally, latestArtifactsRef]);

  // Drag-depth tracking for the workspace's own visual feedback (independent of CardGrid's).
  const onDragEnter = useCallback((e: React.DragEvent) => {
    if (!(isFileDrag(e.dataTransfer) || isArtifactsDrag(e.dataTransfer))) return;
    depthRef.current += 1;
    setDragDepth(depthRef.current);
    setWorkspaceDragKind(isFileDrag(e.dataTransfer) ? 'file' : 'artifacts');
  }, []);

  const onDragLeave = useCallback((e: React.DragEvent) => {
    if (!(isFileDrag(e.dataTransfer) || isArtifactsDrag(e.dataTransfer))) return;
    depthRef.current = Math.max(0, depthRef.current - 1);
    setDragDepth(depthRef.current);
    if (depthRef.current === 0) {
      setWorkspaceDragKind(null);
    }
  }, []);

  const hasRealDockedWorkspace = Boolean(activeWorkspace?.id);
  const shouldShowNoSourceState = !activeSource || (activeSource.type === 'workspace' && !hasRealDockedWorkspace);

  // Workspace-level drop handlers for empty state (when CardGrid isn't rendered)
  const onWorkspaceDragOver = useCallback((e: React.DragEvent) => {
    const artifactDrag = isArtifactsDrag(e.dataTransfer);
    const fileDrag = isFileDrag(e.dataTransfer);

    if (!workspaceId) {
      if (!shouldShowNoSourceState || !artifactDrag) return;
    } else if (!(fileDrag || artifactDrag)) {
      return;
    }
    
    e.preventDefault();
    e.stopPropagation();
    setWorkspaceDragKind(fileDrag ? 'file' : 'artifacts');
    try { 
      if (e.dataTransfer) e.dataTransfer.dropEffect = 'move'; 
    } catch { 
      // ignore
    }
  }, [shouldShowNoSourceState, workspaceId]);

  const parseDraggedArtifactIds = useCallback((e: React.DragEvent): string[] => {
    const resolvedIds = getDroppedArtifactIds(e.dataTransfer);
    if (resolvedIds.length > 0) return resolvedIds;

    try {
      const raw = e.dataTransfer.getData('application/x-agience-artifact');
      if (raw) {
        const parsed = JSON.parse(raw);
        if (parsed && Array.isArray(parsed.ids)) {
          return keyList(parsed.ids);
        }
      }
    } catch {
      // ignore
    }

    try {
      const raw = e.dataTransfer.getData('application/json') || e.dataTransfer.getData('text/plain');
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed?.ids)) return keyList(parsed.ids);
      if (Array.isArray(parsed)) return keyList(parsed);
    } catch {
      const raw = e.dataTransfer.getData('text/plain');
      if (raw) return splitList(raw);
    }

    return [];
  }, []);
  const onWorkspaceDrop = useCallback(async (e: React.DragEvent) => {
    const artifactDrag = isArtifactsDrag(e.dataTransfer);
    const fileDrag = isFileDrag(e.dataTransfer);

    if (!workspaceId) {
      if (!shouldShowNoSourceState || !artifactDrag) return;
    } else if (!(fileDrag || artifactDrag)) {
      return;
    }
    
    e.preventDefault();
    e.stopPropagation();
    resetWorkspaceDragState();

    if (artifactDrag) {
      const draggedIds = parseDraggedArtifactIds(e);
      if (draggedIds.length > 0) {
        if (!workspaceId) {
          await createWorkspaceFromDroppedArtifacts(draggedIds);
        } else {
          handleResolvedDrop(draggedIds, latestArtifactsRef.current.length);
        }
      }
      return;
    }
    
    const files = Array.from(e.dataTransfer.files || []);
    if (files.length) {
      uploadFilesAt(files, latestArtifactsRef.current.length);
    }
  }, [workspaceId, shouldShowNoSourceState, createWorkspaceFromDroppedArtifacts, handleResolvedDrop, parseDraggedArtifactIds, resetWorkspaceDragState, uploadFilesAt]);

  // dragDepth and workspaceDragKind are set by the handlers above for consumers that need to
  // know whether a file or artifact drag is over the workspace (e.g. BrowserHeader drop targets).

  // Themed pale background for browser area
  const browserBg = activeSource?.type === 'workspace'
    ? 'bg-purple-50'
    : activeSource?.type === 'collection'
    ? 'bg-blue-50'
    : 'bg-white';

  // `mode === 'delete'` destroys the artifact (DELETE /artifacts/{id}); otherwise it is unlinked
  // from the collection or workspace it is shown in.
  const handleBrowserRemove = useCallback(async (artifact: Artifact, mode?: CardRemoveMode) => {
    if (!artifact.id) return;

    const actx = safeParseArtifactContext(artifact.context);
    const actxContentType = actx.content_type;
    const resolvedWsId =
      (typeof actx.workspace_id === 'string' ? actx.workspace_id : null) ??
      workspaces.find(w =>
        String(w.id) === String(artifact.id ?? '') ||
        String(w.id) === String(artifact.root_id ?? '') ||
        String(w.id) === String(artifact.collection_id ?? '')
      )?.id ?? null;
    const isInboxRef = actxContentType === WORKSPACE_CONTENT_TYPE && resolvedWsId === inboxWorkspaceId;
    const isPermanent = !isInboxRef && mode === 'delete';

    if (isPermanent) {
      const confirmed = await dangerConfirm.confirm({
        title: CARD_CONFIRM.DELETE_TITLE,
        description: CARD_CONFIRM.DELETE_DESCRIPTION,
        confirmLabel: CARD_CONFIRM.DELETE_CONFIRM,
        cancelLabel: BUTTON_LABELS.CANCEL
      });

      if (!confirmed) return;

      if (!(await deleteArtifact(String(artifact.id)))) return;
      undockWorkspaceIfNeeded(artifact);
      const deletedId = String(artifact.id);
      setSourceArtifacts(prev => withoutKey(withoutKey(prev, c => c.id, deletedId), c => c.root_id ?? '', deletedId));
      return;
    }

    const removableId = String(artifact.root_id ?? artifact.id);
    if (!removableId) return;

    undockWorkspaceIfNeeded(artifact);

    if (activeSource?.type === 'collection') {
      try {
        const collectionId = activeSource.id;
        announceRemoval(await removeArtifactFromCollection(collectionId, removableId), {
          from: 'this collection',
          relink: () => addArtifactToCollection(collectionId, removableId),
          after: () => {
            getCollectionArtifacts(collectionId)
              .then(arts => setSourceArtifacts(arts as Artifact[]))
              .catch(() => {});
          },
        });
      } catch (err) {
        toast.error('Could not remove the artifact from this collection', {
          description: errorDetail(err, err instanceof Error ? err.message : 'Unknown error'),
        });
        return;
      }
      setSourceArtifacts(prev => withoutKey(prev, c => c.root_id ?? c.id, removableId));
      return;
    }

    // Through the workspace store: this view's list is the store's list, refilled from it on every
    // change, so a removal made only here came back. 2026-10-13, a tester: Remove answered 200 and
    // the card stayed.
    if (activeSource?.type === 'workspace' && workspaceId && workspaceId === activeWorkspace?.id) {
      await removeArtifact(removableId);
      return;
    }
    if (activeSource?.type === 'workspace' && workspaceId) {
      try {
        announceRemoval(await removeWorkspaceArtifact(workspaceId, removableId), {
          from: 'this workspace',
          relink: () => addArtifactToCollection(workspaceId, removableId),
        });
      } catch (err) {
        // The server's own words, such as why an item made here stays (2026-11-15, the Tester).
        toast.error('Could not remove the artifact', { description: errorDetail(err, '') || undefined });
        return;
      }
      setSourceArtifacts(prev => withoutKey(prev, c => c.root_id ?? c.id, removableId));
      return;
    }

    await removeArtifact(String(artifact.id));
  }, [activeSource?.id, activeSource?.type, activeWorkspace?.id, dangerConfirm, deleteArtifact, inboxWorkspaceId, removeArtifact, undockWorkspaceIfNeeded, workspaceId, workspaces]);

  browserRemoveRef.current = (artifact: Artifact) => handleBrowserRemove(artifact);

  // The container on screen, by the title it is shown by, as remove labels name it. 2026-10-23, a
  // tester: the toolbar said "Remove from Inbox" and the card menu "Remove from workspace".
  const containerName = activeSource?.type === 'collection'
    ? (collections.find(c => String(c.id) === String(activeSource.id))?.name || 'collection')
    : workspaceId && workspaceId === inboxWorkspaceId ? 'Inbox'
    : (activeWorkspace?.name || 'workspace');
  const namedSource = useMemo(
    () => (activeSource ? { ...activeSource, noun: containerName } : activeSource),
    [activeSource, containerName],
  );

  const renderArtifactSection = useCallback((sectionArtifacts: Artifact[], sectionKey: string) => {
    if (sectionArtifacts.length === 0) return null;

    if (viewMode === 'grid') {
      return (
        <div className={sectionKey === 'primary' ? 'px-4 pt-4 pb-4 min-h-full' : 'px-4 pt-4 pb-4'}>
          <CardGrid
            artifacts={sectionArtifacts}
            artifactCountsById={artifactCountsByOwnerId}
            selectable
            draggable={sectionKey === 'primary'}
            fillHeight={true}
            selectedIds={selectedArtifactIds}
            isSelected={(id) => selectedArtifactIds.includes(id)}
            activeSource={namedSource}
            onArtifactMouseDown={(id, e, shownIds) => {
              selectArtifact(id, e, shownIds);
              onArtifactSelect?.(id);
            }}
            onOpenArtifact={onOpenArtifact}
            onAssignCollections={(artifact) => {
              openAssignFor(artifact);
            }}

            onRemove={handleBrowserRemove}
            deleteEnabled
            onSelectionAction={handleSelectionAction}
            onAddToWorkspace={addToWorkspace}
            onOrder={sectionKey === 'primary' ? ((_ids, moved) => moveArtifacts(moved.ids, moved.beforeId)) : undefined}
            onFileDrop={sectionKey === 'primary' && !!workspaceId ? ((index, files) => uploadFilesAt(files, index)) : undefined}
            onArtifactDrop={sectionKey === 'primary' && (!!workspaceId || activeSource?.type === 'collection')
              ? ((index, draggedIds, dragPayload) => handleResolvedDrop(draggedIds, index, dragPayload))
              : undefined}
          />
        </div>
      );
    }

    return (
      <div className="px-4 pt-4 pb-4">
        <CardList
          artifacts={sectionArtifacts}
          artifactCountsById={artifactCountsByOwnerId}
          selectable
          draggable={sectionKey === 'primary'}
          isSelected={(id) => selectedArtifactIds.includes(id)}
          onArtifactMouseDown={(id, e, shownIds) => {
            selectArtifact(id, e as React.MouseEvent, shownIds);
            onArtifactSelect?.(id);
          }}
          onEditArtifactOpen={() => {
            // Preview pane uses current selection.
          }}
          containerNoun={containerName}
          onOpenArtifact={onOpenArtifact}
          onAddToWorkspace={addToWorkspace}
          onAssignCollections={(artifact: Artifact) => {
            openAssignFor(artifact);
          }}
          onRemove={handleBrowserRemove}
          deleteEnabled
          onSelectionAction={handleSelectionAction}
          onArchive={async (artifact: Artifact) => {
            if (!artifact.id || !updateArtifact) return;
            undockWorkspaceIfNeeded(artifact);
            await updateArtifact({ id: String(artifact.id), state: 'archived' });
          }}
          onRestore={async (artifact: Artifact) => {
            if (artifact.id && updateArtifact) {
              await updateArtifact({ id: String(artifact.id), state: 'live' });
              // A restored member returns to the live list, which the archived listing left out.
              if (activeSource?.type === 'collection') {
                getCollectionArtifacts(activeSource.id)
                  .then(arts => setSourceArtifacts(arts as Artifact[]))
                  .catch(err => console.error('Failed to reload collection artifacts:', err));
              }
              reloadView();
            }
          }}
          onReorder={sectionKey === 'primary' ? ((artifactId, targetIndex) => {
            const newOrder = [...sectionArtifacts];
            const fromIndex = newOrder.findIndex(c => String(c.id) === artifactId);
            if (fromIndex !== -1) {
              const [artifact] = newOrder.splice(fromIndex, 1);
              newOrder.splice(targetIndex, 0, artifact);
              const after = newOrder[targetIndex + 1];
              moveArtifacts([artifactId], after ? String(after.id) : null);
            }
          }) : undefined}
          onFileDrop={sectionKey === 'primary' && !!workspaceId ? ((files, index) => uploadFilesAt(files, index || 0)) : undefined}
        />
      </div>
    );
  }, [activeSource, namedSource, containerName, addToWorkspace, artifactCountsByOwnerId, handleBrowserRemove, handleResolvedDrop, handleSelectionAction, reloadView, openAssignFor, onArtifactSelect, onOpenArtifact, moveArtifacts, selectArtifact, selectedArtifactIds, undockWorkspaceIfNeeded, updateArtifact, uploadFilesAt, viewMode, workspaceId]);

  return (
    <LockedActionsContext.Provider value={lockedActions}>
    <div className="h-full flex flex-col">
      
      <BrowserHeader
        activeSource={activeSource}
        viewChoices={viewChoices}
        onToggleFilters={() => setFiltersOpen(!filtersOpen)}
        filtersOpen={filtersOpen}
        hasActiveFilter={activeFilter !== 'all'}
        activeFilter={activeFilter}
        viewMode={viewMode}
        onViewModeChange={(mode) => setViewMode(mode)}
        sortMode={searchSortMode}
        onSortChange={onSearchSortChange}
        onNewArtifact={handleOpenTypePicker}
        onUploadFiles={workspaceId ? ((files) => uploadFilesAt(files, latestArtifactsRef.current.length)) : undefined}
        onCreateWorkspace={handleCreateWorkspace}
        onDropWorkspace={handleDropWorkspace}
        onDropOnTab={handleDropOnTab}
        onDeleteWorkspace={handleDeleteWorkspace}
        onRenameWorkspace={handleRenameWorkspace}
      />

      {/* Invites addressed to this person arrive in their Inbox (FR-004). */}
      {workspaceId && inboxWorkspaceId && String(workspaceId) === String(inboxWorkspaceId) && (
        <IncomingInvites />
      )}

      {/* Filter Chips - Always visible so the grey bar stays as a consistent landmark */}
      <FilterChips
        chips={view?.chips ?? []}
        kinds={view?.kinds ?? []}
        activeStates={activeStateFilters}
        activeContentTypes={activeContentTypeFilters}
        hiddenContentTypes={hiddenContentTypeFilters}
        viewMode={viewMode}
        onViewModeChange={(mode) => setViewMode(mode)}
        onStateToggle={handleStateFilterToggle}
        onContentTypeToggle={handleContentTypeFilterToggle}
        onHiddenContentTypeToggle={handleHiddenContentTypeToggle}
        onClearAll={handleClearAllFilters}
      />

      {activeSource?.type === 'workspace' && stackedArtifacts.sections.length > 0 && (
        <div className="border-b border-gray-200 bg-white px-4 py-2">
          <button
            type="button"
            onClick={() => setStackArtifactFamilies((prev) => !prev)}
            className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${stackArtifactFamilies ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'}`}
          >
            {stackArtifactFamilies ? 'Artifact stacks on' : 'Artifact stacks off'}
          </button>
          <span className="ml-3 text-xs text-gray-500">
            Group artifacts by owning source artifact when possible, with family fallbacks for anything unresolved.
          </span>
        </div>
      )}

      {/* Filter Bar (with Sort and View) - Sliding Drawer */}
      <FilterBar
        counts={counts}
        activeFilter={activeFilter}
        onFilterChange={setActiveFilter}
        sortBy={sortBy}
        onSortChange={setSortBy}
        viewMode={viewMode}
        onViewChange={(view) => setViewMode(view === 'compact' ? 'list' : view)}
        isOpen={filtersOpen}
      />

      {/* Main Content Area */}
      <div
        id="workspace-root"
        data-accept-drop="workspace"
        className={[
          "relative flex-1 overflow-y-auto transition-shadow",
          browserBg,
          "ring-0"
        ].join(" ")}
        onClick={(e) => {
          // Deselect when clicking anywhere in the workspace that isn't on a card
          if (!(e.target as Element).closest('[data-testid^="artifact-"]')) {
            unselectAllArtifacts();
          }
        }}
        onDoubleClick={(e) => {
          if (activeSource?.type !== 'workspace') return;
          const target = e.target as Element;
          if (target.closest('[data-testid^="artifact-"]')) return;
          handleOpenTypePicker();
        }}
        onDragEnter={onDragEnter}
        onDragLeave={onDragLeave}
        onDragOver={onWorkspaceDragOver}
        onDrop={onWorkspaceDrop}
      >
        {/* Empty States */}
        {shouldShowNoSourceState ? (
          <EmptyState
            type="no-source"
            onCreateWorkspace={handleCreateWorkspace}
            onCreateCard={canCreateCardInInbox ? handleCreateCardInInbox : undefined}
          />
        ) : filteredArtifacts.length === 0 && filtersHideEverything ? (
          <EmptyState
            type="no-search-results"
            onClearFilters={isAnyFilterActive ? handleClearEveryFilter : undefined}
          />
        ) : filteredArtifacts.length === 0 ? (
          <EmptyState
            type="no-artifacts"
            isInbox={activeSource?.type === 'workspace' && Boolean(inboxWorkspaceId) && workspaceId === inboxWorkspaceId}
            onCreateWorkspace={handleCreateWorkspace}
            onCreateCard={activeSource?.type === 'workspace' ? handleOpenTypePicker : undefined}
          />
        ) : (
          shouldUseArtifactStacks ? (
            <div className="pb-4">
              {stackedArtifacts.primaryArtifacts.length > 0 && renderArtifactSection(stackedArtifacts.primaryArtifacts, 'primary')}
              {stackedArtifacts.sections.map((section) => {
                const collapsed = collapsedArtifactSections[section.id] ?? section.defaultCollapsed ?? true;
                return (
                  <div key={section.id} className="px-4 pb-4">
                    <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
                      <button
                        type="button"
                        onClick={() => toggleArtifactSection(section.id)}
                        className="flex w-full items-center justify-between px-4 py-3 text-left"
                      >
                        <div>
                          <div className="text-sm font-semibold text-slate-900">{section.title}</div>
                          <div className="text-xs text-slate-500">{section.artifacts.length} artifacts</div>
                        </div>
                        <div className="text-xs font-medium text-slate-600">{collapsed ? 'Expand' : 'Collapse'}</div>
                      </button>
                      {!collapsed && renderArtifactSection(section.artifacts, section.id)}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            renderArtifactSection(filteredArtifacts, 'primary')
          )
        )}
      </div>

      {/* Multi-Artifact Toolbar */}
      {showFloatingToolbar && (
        <MultiCardToolbar
          selectedCount={selectedArtifactIds.length}
          onArchive={handleBulkArchive}
          onAddTags={handleBulkAddTags}
          onMove={handleBulkMove}
          onDelete={handleBulkDelete}
          onDrop={handleBulkDrop}
          dropTitle={`Remove from ${containerName}`}
          onClear={unselectAllArtifacts}
          canDelete={bulkCanDelete}
          hasLive={bulkHasLive}
          hasArchived={bulkSelectedArtifacts.some(a => a.state === 'archived')}
          onRestore={handleBulkRestore}
        />
      )}

      {addToWorkspacePicker}
      <WorkspaceDetailModal
        open={offeredWorkspaceName !== null}
        mode="create"
        initial={newWorkspaceInitial}
        onSave={createNamedWorkspace}
        onClose={() => setOfferedWorkspaceName(null)}
      />
      <CollectionPicker
        open={showBulkCollectionPicker && assignHeld !== null}
        onClose={() => { setShowBulkCollectionPicker(false); setAssignIds(null); }}
        onSelect={handleBulkSelectCollections}
        selectedCollectionIds={assignHeld?.all ?? []}
        partialCollectionIds={assignHeld?.some ?? []}
        multiple={true}
        title={(() => {
          const n = (assignIds ?? selectedArtifactIds).length;
          return `Assign ${n} Artifact${n === 1 ? '' : 's'} to Collections`;
        })()}
      />

      <BulkTagDialog
        open={showBulkTagDialog}
        onClose={() => setShowBulkTagDialog(false)}
        onApply={handleBulkApplyTags}
        selectedCount={selectedArtifactIds.length}
      />

      {/* Edit Modal */}
      {editArtifact && (
        <ArtifactEditModal
          artifact={editArtifact as unknown as Artifact}
          onSave={handleSave}
          onClose={handleClose}
        />
      )}

      <CardTypePickerDialog
        open={isArtifactTypePickerOpen}
        onOpenChange={setIsArtifactTypePickerOpen}
        onSelect={handleSelectArtifactType}
      />
    </div>
    </LockedActionsContext.Provider>
  );
}

type ArtifactSection = {
  id: string;
  title: string;
  artifacts: Artifact[];
  defaultCollapsed?: boolean;
};
