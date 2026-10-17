import { useCallback, useEffect, useMemo, useState } from 'react';
import { LayoutGrid, List, Plus } from 'lucide-react';
import { toast } from 'sonner';

import CardGrid from '@/components/common/CardGrid';
import CardList from '@/components/common/CardList';
import { addArtifactToCollection, listCollectionArtifacts, removeArtifactFromCollection, subscribeCollectionEvents } from '@/api/collections';
import { AGIENCE_DRAG_CONTENT_TYPE, getDroppedArtifactIds } from '@/dnd/agienceDrag';
import { useWorkspace } from '@/hooks/useWorkspace';
import type { Artifact } from '@/context/workspace/workspace.types';
import { getStableArtifactId } from '@/utils/artifact-identifiers';
import type { CardRemoveMode } from '@/utils/artifact-permissions';
import { useConfirm } from '@/context/dialog/useConfirm';
import { BUTTON_LABELS, CARD_CONFIRM } from '@/constants/strings';
import { addArtifactToWorkspace } from '@/api/workspaces';
import CardTypePickerDialog from '@/components/browser/CardTypePickerDialog';
import { getContentTypeById } from '@/registry/content-types';
import { safeParseArtifactContext, stringifyArtifactContext } from '@/utils/artifactContext';
import { WORKSPACE_CONTENT_TYPE } from '@/utils/content-type';
import { errorDetail } from '@/utils/errorDetail';
import { artifactTitle, markNewCard, nextUntitledTitle } from '@/utils/untitled';
import { announceRemoval } from '@/utils/removal';

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
      ids: payload.ids.map(String).filter(Boolean),
      versionIds: Array.isArray(payload.versionIds) ? payload.versionIds.map(String).filter(Boolean) : [],
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
  onOpenArtifact?: (artifact: Artifact) => void;
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
  const [pickerOpen, setPickerOpen] = useState(false);

  const [memberItems, setMemberItems] = useState<Artifact[]>([]);
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
      onArtifactUpdated: (artifact) => {
        setMemberItems(prev =>
          prev.map(c => {
            const cKey = String(c.root_id ?? c.id);
            const aKey = String((artifact as Artifact).root_id ?? artifact.id);
            return cKey === aKey ? { ...c, ...artifact } as Artifact : c;
          })
        );
      },
      onArtifactDeleted: (artifactId) => {
        setMemberItems(prev =>
          prev.filter(c => String(c.root_id ?? c.id) !== String(artifactId))
        );
      },
      onCollectionRefreshed: () => {
        void reloadArtifacts();
      },
    });

    return unsubscribe;
  }, [collectionId, reloadArtifacts]);

  const pendingWorkspaceItems = useMemo(() => {
    if (!collectionId) return [] as Artifact[];

    return workspaceArtifacts.filter((candidate) => {
      // An archived card stays in the workspace store until its next refresh; it is not a member
      // anyone lists, so it is not shown here either.
      if (candidate.state === 'archived') return false;
      const memberIds = Array.isArray(candidate.committed_collection_ids)
        ? candidate.committed_collection_ids.map(String)
        : [];

      return memberIds.includes(collectionId);
    });
  }, [collectionId, workspaceArtifacts]);

  const items = useMemo(() => {
    const byId = new Map<string, Artifact>();

    const addItem = (candidate: Artifact) => {
      const key = String(candidate.root_id ?? getStableArtifactId(candidate) ?? '');
      if (!key) return;
      if (!byId.has(key)) byId.set(key, candidate);
    };

    memberItems.forEach(addItem);
    pendingWorkspaceItems.forEach(addItem);

    return Array.from(byId.values());
  }, [memberItems, pendingWorkspaceItems]);

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
        announceRemoval(await removeArtifactFromCollection(collectionId, rootId), {
          from: `this ${noun}`,
          relink: () => addArtifactToCollection(collectionId, rootId),
          after: () => { void reloadArtifacts(); },
        });
      } catch (err) {
        toast.error(`Could not remove the card from this ${noun}`, {
          description: errorDetail(err, err instanceof Error ? err.message : 'Unknown error'),
        });
        return;
      }
      // The workspace store's copy still lists this container among its memberships, and this view
      // adds every store card that does; drop the membership there too, or the card comes back.
      // 2026-10-13, a tester: Remove answered 200 `removed: true` and the card stayed.
      for (const card of workspaceArtifacts) {
        if (String(card.root_id ?? card.id ?? '') !== rootId || !Array.isArray(card.committed_collection_ids)) continue;
        patchArtifactLocally({
          id: card.id,
          committed_collection_ids: card.committed_collection_ids.filter((c) => String(c) !== collectionId),
        });
      }
    }
    setMemberItems((prev) => prev.filter((candidate) => String(candidate.root_id ?? candidate.id ?? '') !== rootId));
  }, [collectionId, dangerConfirm, deleteArtifact, noun, patchArtifactLocally, reloadArtifacts, workspaceArtifacts]);

  // Create a card in this container: the picker the browser's "New card" uses, with the new
  // artifact homed here rather than in the active workspace.
  const handleCreate = useCallback(async (contentType: string) => {
    setPickerOpen(false);
    if (!collectionId) return;
    const type = getContentTypeById(contentType);
    const title = nextUntitledTitle(`Untitled ${type?.label || 'Artifact'}`, items.map(artifactTitle));
    try {
      const created = await addArtifactToWorkspace(collectionId, {
        content: '',
        content_type: contentType,
        context: stringifyArtifactContext({ title }),
      }) as Artifact;
      if (created.id) markNewCard(String(created.id), title);
      await reloadArtifacts();
      onOpenArtifact?.(created);
    } catch (err) {
      toast.error('Could not create card', {
        description: errorDetail(err, err instanceof Error ? err.message : 'Unknown error'),
      });
    }
  }, [collectionId, items, onOpenArtifact, reloadArtifacts]);

  const applyDroppedArtifacts = useCallback(async (
    ids: string[],
    payload?: { sourceType?: string; workspaceId?: string; versionIds?: string[] },
  ) => {
    if (!collectionId || !ids.length) return;

    const versionIds = Array.isArray(payload?.versionIds)
      ? payload.versionIds.map(String).filter(Boolean)
      : [];
    const idsToAdd = (versionIds.length > 0 ? versionIds : ids)
      .filter((draggedId) => String(draggedId) !== String(collectionId));

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
            title={`New card in this ${noun}`}
          >
            <Plus className="h-3.5 w-3.5" />
            New card
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
              activeSource={collectionId ? { type: 'collection', id: collectionId, noun } : null}
              onOpenArtifact={onOpenArtifact}
              onRemove={handleRemove}
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
            containerNoun={noun}
            onOpenArtifact={onOpenArtifact}
            onRemove={handleRemove}
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
    </div>
  );
}