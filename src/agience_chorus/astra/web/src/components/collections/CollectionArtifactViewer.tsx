import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { LayoutGrid, List, Plus } from 'lucide-react';
import { toast } from 'sonner';

import CardGrid from '@/components/common/CardGrid';
import CardList from '@/components/common/CardList';
import { addArtifactToCollection, changeMemberships, listCollectionArtifacts, subscribeCollectionEvents, type MembershipItem } from '@/api/collections';
import { CollectionPicker } from '@/components/modals/CollectionPicker';
import { AGIENCE_DRAG_CONTENT_TYPE, getDroppedArtifactIds } from '@/dnd/agienceDrag';
import { useWorkspace } from '@/hooks/useWorkspace';
import type { Artifact } from '@/context/workspace/workspace.types';
import type { CardRemoveMode } from '@/utils/artifact-permissions';
import { useConfirm } from '@/context/dialog/useConfirm';
import { ARTIFACT_CHANGED_EVENT, BUTTON_LABELS, CARD_CONFIRM, MEMBERSHIP_CHANGED_EVENT, changeOf, containerOf } from '@/constants/strings';
import { addArtifactToWorkspace } from '@/api/workspaces';
import CardTypePickerDialog from '@/components/browser/CardTypePickerDialog';
import { getContentTypeById } from '@/registry/content-types';
import { artifactTitle, safeParseArtifactContext } from '@/utils/artifactContext';
import { WORKSPACE_CONTENT_TYPE } from '@/utils/content-type';
import { errorDetail } from '@/utils/errorDetail';
import { announceRemoval } from '@/utils/removal';
import { keyList, withoutKey } from '@/display-state/lists';

type CollectionViewMode = 'grid' | 'list';

function parseDragPayload(dt: DataTransfer) {
  const parseRaw = (raw: string) => {
    if (!raw) return null;
    try {
      return JSON.parse(raw) as {
        ids?: unknown;
        versionIds?: unknown;
        sourceType?: unknown;
        workspaceId?: unknown;
        sourceWorkspaceId?: unknown;
      };
    } catch {
      return null;
    }
  };

  const fromCustom = parseRaw(dt.getData('application/x-agience-artifact'));
  const fromJson = parseRaw(dt.getData('application/json'));
  const payload = fromCustom ?? fromJson;
  const droppedIds = getDroppedArtifactIds(dt);

  if (payload && Array.isArray(payload.ids)) {
    return {
      ids: keyList(payload.ids),
      versionIds: keyList(payload.versionIds),
      sourceType: typeof payload.sourceType === 'string' ? payload.sourceType : undefined,
      sourceWorkspaceId:
        typeof payload.workspaceId === 'string'
          ? payload.workspaceId
          : typeof payload.sourceWorkspaceId === 'string'
            ? payload.sourceWorkspaceId
            : undefined,
    };
  }

  return {
    ids: droppedIds,
      versionIds: [],
    sourceType: undefined,
    sourceWorkspaceId: undefined,
  };
}

export default function CollectionArtifactViewer({
  artifact,
  mode,
  onOpenArtifact,
}: {
  artifact: Artifact;
  mode?: string;
  onOpenArtifact?: (artifact: Artifact, options?: { startInEditMode?: boolean }) => void;
}) {
  const { artifacts: workspaceArtifacts, deleteArtifact, patchArtifactLocally } = useWorkspace();
  const dangerConfirm = useConfirm();

  // A collection artifact is the collection. Its id is the container_id
  // for the list API. No prefix decoding or context lookups needed.
  const collectionId = useMemo(() => artifact.id ?? '', [artifact.id]);
  // A workspace opened in a card window is listed here like a collection; its labels say workspace.
  const isWorkspace = useMemo(() => {
    const declared = (artifact as { content_type?: string }).content_type
      ?? safeParseArtifactContext(artifact.context).content_type;
    return declared === WORKSPACE_CONTENT_TYPE;
  }, [artifact]);
  const noun = isWorkspace ? 'workspace' : 'collection';
  // Remove labels name this container by its title ("Remove from REG-WS").
  const removeTarget = artifactTitle(artifact) || noun;
  const [pickerOpen, setPickerOpen] = useState(false);
  // The card whose collections the context menu's "Assign to collections…" is changing (BUG-020:
  // the item did nothing in a collection window, where no handler was passed).
  const [assignFor, setAssignFor] = useState<Artifact | null>(null);
  // The containers holding the artifact being assigned, as Mantle reads them; the picker opens on it.
  const [assignHeld, setAssignHeld] = useState<string[] | null>(null);
  useEffect(() => {
    setAssignHeld(null);
    if (!assignFor) return;
    let live = true;
    changeMemberships([String(assignFor.id)])
      .then(m => { if (live) setAssignHeld(m.all); })
      .catch(() => { if (live) setAssignHeld([]); });
    return () => { live = false; };
  }, [assignFor]);

  const [memberItems, setMemberItems] = useState<Artifact[]>([]);
  const memberItemsRef = useRef<Artifact[]>(memberItems);
  memberItemsRef.current = memberItems;
  const [isLoading, setIsLoading] = useState(false);
  const [viewMode, setViewMode] = useState<CollectionViewMode>(mode === 'list' ? 'list' : 'grid');
  const [dropActive, setDropActive] = useState(false);

  useEffect(() => {
    setViewMode(mode === 'list' ? 'list' : 'grid');
  }, [mode]);

  const reloadArtifacts = useCallback(async () => {
    if (!collectionId) {
      setMemberItems([]);
      return;
    }

    setIsLoading(true);
    try {
      const next = await listCollectionArtifacts(collectionId);
      setMemberItems(next as Artifact[]);
    } catch (error) {
      console.error('Failed to load collection artifacts:', error);
      setMemberItems([]);
    } finally {
      setIsLoading(false);
    }
  }, [collectionId]);

  useEffect(() => {
    void reloadArtifacts();
  }, [reloadArtifacts]);

  // One change to a member: an archived one leaves the window, a listed one takes the change, and a
  // live one not listed (a restore) is read in with the rest.
  const applyChange = useCallback((artifact: Artifact) => {
    const aKey = String(artifact.root_id ?? artifact.id);
    const listed = (c: Artifact) => String(c.root_id ?? c.id) === aKey || String(c.id) === String(artifact.id);
    if (artifact.state === 'archived') {
      setMemberItems(prev => withoutKey(prev, listed, true));
      return;
    }
    if (!memberItemsRef.current.some(listed)) {
      if (artifact.state === 'live') void reloadArtifacts();
      return;
    }
    setMemberItems(prev => prev.map(c => (listed(c) ? { ...c, ...artifact } as Artifact : c)));
  }, [reloadArtifacts]);

  // Subscribe to real-time collection change events via SSE
  useEffect(() => {
    if (!collectionId) return;

    const unsubscribe = subscribeCollectionEvents(collectionId, {
      onArtifactCreated: (artifact) => {
        setMemberItems(prev => {
          const key = String((artifact as Artifact).root_id ?? artifact.id);
          if (prev.some(c => String(c.root_id ?? c.id) === key)) return prev;
          return [...prev, artifact as Artifact];
        });
      },
      onArtifactUpdated: (artifact) => { applyChange(artifact as Artifact); },
      onArtifactDeleted: (artifactId) => {
        setMemberItems(prev => withoutKey(prev, c => c.root_id ?? c.id, artifactId));
      },
      onCollectionRefreshed: () => {
        void reloadArtifacts();
      },
    });

    return unsubscribe;
  }, [collectionId, applyChange, reloadArtifacts]);

  // A change saved anywhere in the app, as this window's members show it. 2026-10-23, a tester
  // restored a note with this workspace's window open, and it appeared only after the window was
  // closed and opened again; 2026-10-27, measured in a browser, a member edited in its own window
  // kept its old title and preview here.
  useEffect(() => {
    const onChange = (e: Event) => {
      const change = changeOf(e);
      if (change) applyChange(change as unknown as Artifact);
    };
    window.addEventListener(ARTIFACT_CHANGED_EVENT, onChange);
    return () => window.removeEventListener(ARTIFACT_CHANGED_EVENT, onChange);
  }, [applyChange]);

  // A membership saved anywhere in the app that names this container: Mantle lists the members again.
  useEffect(() => {
    if (!collectionId) return;
    const onMembership = (e: Event) => { if (containerOf(e) === collectionId) void reloadArtifacts(); };
    window.addEventListener(MEMBERSHIP_CHANGED_EVENT, onMembership);
    return () => window.removeEventListener(MEMBERSHIP_CHANGED_EVENT, onMembership);
  }, [collectionId, reloadArtifacts]);

  // The members are what Mantle lists for this container.
  const items = memberItems;

  // Show where Mantle says an artifact is held, on the workspace store's copy and in this list.
  const patchMemberships = useCallback((now: MembershipItem) => {
    const held = { committed_collection_ids: now.committed_collection_ids, container_ids: now.container_ids,
      containers: now.containers };
    for (const card of workspaceArtifacts) {
      if (String(card.root_id ?? card.id ?? '') === now.root_id) patchArtifactLocally({ id: card.id, ...held });
    }
    setMemberItems(prev => prev.map(c => (String(c.root_id ?? c.id ?? '') === now.root_id ? { ...c, ...held } : c)));
  }, [patchArtifactLocally, workspaceArtifacts]);

  // `mode === 'delete'` destroys the artifact (DELETE /artifacts/{id}) after a confirmation;
  // otherwise it is unlinked from this collection.
  const handleRemove = useCallback(async (item: Artifact, mode?: CardRemoveMode) => {
    if (!collectionId) return;

    const rootId = String(item.root_id ?? item.id ?? '').trim();
    if (!rootId) return;

    if (mode === 'delete') {
      const confirmed = await dangerConfirm.confirm({
        title: CARD_CONFIRM.DELETE_TITLE,
        description: CARD_CONFIRM.DELETE_DESCRIPTION,
        confirmLabel: CARD_CONFIRM.DELETE_CONFIRM,
        cancelLabel: BUTTON_LABELS.CANCEL,
      });
      if (!confirmed) return;
      if (!(await deleteArtifact(String(item.id ?? rootId)))) return;
    } else {
      try {
        const answer = await changeMemberships([rootId], { remove: [collectionId] });
        if (answer.failed.length) throw new Error(answer.failed[0].detail);
        const [now] = answer.items;
        announceRemoval({ id: now?.id ?? rootId, removed: true, container_id: collectionId,
          archived: answer.archived.length > 0 }, {
          from: `this ${noun}`,
          relink: () => addArtifactToCollection(collectionId, rootId),
          after: () => { void reloadArtifacts(); },
        });
        // The workspace store's copy shows what Mantle now says holds it.
        if (now) patchMemberships(now);
      } catch (err) {
        toast.error(`Could not remove the artifact from this ${noun}`, {
          description: errorDetail(err, err instanceof Error ? err.message : 'Unknown error'),
        });
        return;
      }
    }
    setMemberItems((prev) => withoutKey(prev, (candidate) => candidate.root_id ?? candidate.id ?? '', rootId));
  }, [collectionId, dangerConfirm, deleteArtifact, noun, patchMemberships, reloadArtifacts]);

  // Create an artifact in this container: the picker the browser's "New artifact" uses, with the new
  // artifact homed here rather than in the active workspace.
  const handleCreate = useCallback(async (contentType: string) => {
    setPickerOpen(false);
    if (!collectionId) return;
    const type = getContentTypeById(contentType);
    try {
      const created = await addArtifactToWorkspace(collectionId, {
        content: '',
        content_type: contentType,
      }) as Artifact;
      await reloadArtifacts();
      onOpenArtifact?.(created, type?.states.includes('edit') ? { startInEditMode: true } : undefined);
    } catch (err) {
      toast.error('Could not create the artifact', {
        description: errorDetail(err, err instanceof Error ? err.message : 'Unknown error'),
      });
    }
  }, [collectionId, onOpenArtifact, reloadArtifacts]);

  const applyDroppedArtifacts = useCallback(async (
    ids: string[],
    payload?: { sourceType?: string; workspaceId?: string; versionIds?: string[] },
  ) => {
    if (!collectionId || !ids.length) return;

    const versionIds = keyList(payload?.versionIds);
    const idsToAdd = withoutKey(versionIds.length > 0 ? versionIds : ids, (draggedId) => draggedId, collectionId);

    for (const draggedId of idsToAdd) {
      await addArtifactToCollection(collectionId, draggedId);
    }
    await reloadArtifacts();
  }, [collectionId, reloadArtifacts]);

  const handleDropIntoCollection = useCallback(async (dt: DataTransfer) => {
    if (!collectionId) return;
    const { ids, versionIds, sourceType, sourceWorkspaceId } = parseDragPayload(dt);
    if (!ids.length) return;
    await applyDroppedArtifacts(ids, {
      sourceType,
      workspaceId: sourceWorkspaceId,
      versionIds,
    });
  }, [applyDroppedArtifacts, collectionId]);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    // During dragover only `types` is readable (getData returns "" until drop),
    // so gate on the MIME keys. Accept both drag conventions — the legacy
    // card-grid payload and the shared agienceDrag payload — otherwise drags from
    // list view / floating windows / sidebar / palette never activate this target.
    const types = Array.from(e.dataTransfer.types ?? []);
    const hasArtifactPayload =
      types.includes('application/x-agience-artifact') ||
      types.includes(AGIENCE_DRAG_CONTENT_TYPE);
    if (!hasArtifactPayload) return;
    e.preventDefault();
    e.stopPropagation();
    setDropActive(true);
    try {
      e.dataTransfer.dropEffect = 'move';
    } catch {
      // ignore
    }
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    const current = e.currentTarget as HTMLElement;
    const related = e.relatedTarget as Node | null;
    if (!related || !current.contains(related)) {
      setDropActive(false);
    }
  }, []);

  const handleDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDropActive(false);
    await handleDropIntoCollection(e.dataTransfer);
  }, [handleDropIntoCollection]);

  const assignCollections = useCallback(async (ids: string[]) => {
    const card = assignFor;
    if (!card) return;
    try {
      const { items: [now], failed } = await changeMemberships([String(card.id)], { held: ids });
      if (failed.length) toast.error('Could not change every collection', { description: failed[0].detail });
      if (now) patchMemberships(now);
    } catch (err) {
      toast.error('Could not change every collection', { description: errorDetail(err, 'Some changes were not saved') });
    }
    setAssignFor(null);
  }, [assignFor, patchMemberships]);

  return (
    <div
      className={`h-full min-h-0 bg-white flex flex-col ${dropActive ? 'ring-2 ring-blue-500 ring-inset' : ''}`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <div className="flex items-center justify-between border-b border-gray-200 bg-gray-50 px-4 py-2">
        <div className="flex items-center gap-3">
          <div className="text-xs text-gray-500">
            {isLoading ? 'Loading artifacts...' : `${items.length} artifact${items.length === 1 ? '' : 's'}`}
          </div>
          <button
            type="button"
            onClick={() => setPickerOpen(true)}
            className="inline-flex h-7 items-center gap-1 rounded bg-purple-600 px-2 text-xs font-medium text-white hover:bg-purple-700"
            title={`New artifact in this ${noun}`}
          >
            <Plus className="h-3.5 w-3.5" />
            New artifact
          </button>
        </div>
        <div className="inline-flex items-center rounded-md border border-gray-300 bg-white p-0.5 shadow-sm">
          <button
            type="button"
            className={`inline-flex h-7 w-7 items-center justify-center rounded ${viewMode === 'grid' ? 'bg-blue-600 text-white' : 'text-gray-600 hover:bg-gray-100'}`}
            aria-label="Grid view"
            onClick={() => setViewMode('grid')}
          >
            <LayoutGrid className="h-4 w-4" />
          </button>
          <button
            type="button"
            className={`inline-flex h-7 w-7 items-center justify-center rounded ${viewMode === 'list' ? 'bg-blue-600 text-white' : 'text-gray-600 hover:bg-gray-100'}`}
            aria-label="List view"
            onClick={() => setViewMode('list')}
          >
            <List className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="flex-1 min-h-0">
        {viewMode === 'grid' ? (
          <div className="h-full overflow-auto px-4 py-4">
            <CardGrid
              artifacts={items}
              selectable
              draggable
              fillHeight
              activeSource={collectionId ? { type: 'collection', id: collectionId, noun: removeTarget } : null}
              onOpenArtifact={onOpenArtifact}
              onRemove={handleRemove}
              onAssignCollections={setAssignFor}
              deleteEnabled
              onArtifactDrop={(_insertIndex, draggedIds, dragPayload) => {
                void applyDroppedArtifacts(draggedIds, {
                  sourceType: dragPayload?.sourceType,
                  workspaceId: dragPayload?.workspaceId,
                  versionIds: dragPayload?.versionIds,
                });
              }}
            />
          </div>
        ) : (
          <CardList
            artifacts={items}
            selectable
            draggable
            sourceCollectionId={collectionId || undefined}
            containerNoun={removeTarget}
            onOpenArtifact={onOpenArtifact}
            onRemove={handleRemove}
            onAssignCollections={setAssignFor}
            deleteEnabled
            onArtifactDrop={(_insertIndex, draggedIds, dragPayload) => {
              void applyDroppedArtifacts(draggedIds, {
                sourceType: dragPayload?.sourceType,
                workspaceId: dragPayload?.workspaceId,
                versionIds: dragPayload?.versionIds,
              });
            }}
          />
        )}
      </div>

      <CardTypePickerDialog open={pickerOpen} onOpenChange={setPickerOpen} onSelect={handleCreate} />
      {assignFor !== null && assignHeld !== null && (
      <CollectionPicker
        open
        onClose={() => setAssignFor(null)}
        onSelect={(ids) => { void assignCollections(ids); }}
        selectedCollectionIds={assignHeld}
        multiple={true}
        title="Assign to Collections"
      />
      )}
    </div>
  );
}