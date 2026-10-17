// context/workspace/WorkspaceProvider.tsx
import {
  useState, useEffect, useCallback, useMemo, useRef, ReactNode, MouseEvent,
} from 'react';
import {
  listWorkspaceArtifacts,
  addArtifactToWorkspace,
  importCollectionArtifactToWorkspace,
  updateWorkspaceArtifact,
  removeWorkspaceArtifact,
  deleteWorkspaceArtifact,
  orderWorkspaceArtifacts,
  subscribeWorkspaceEvents,
} from '../../api/workspaces';
import { WorkspaceContext } from './WorkspaceContext';
import { Artifact } from './workspace.types';
import { useWorkspaces } from '../workspaces/WorkspacesContext';
import { toast } from 'sonner';
import { safeParseArtifactContext, stringifyArtifactContext } from '@/utils/artifactContext';
import { midKey, afterKey } from '../../utils/fractional-index';
import { extractInformation } from '../../api/agent';
import { errorDetail } from '../../utils/errorDetail';
import { announceRemoval } from '../../utils/removal';
import { addArtifactToCollection } from '../../api/collections';
import { trashArtifact } from '../../api/artifacts';
import { takeNewCard } from '../../utils/untitled';
import { OPEN_TRASH_EVENT, TRASH_RETENTION_DAYS } from '../../constants/strings';

type UpdateArtifactPayload = {
  state?: Artifact['state'];
  context?: string;
  content?: string;
};

type ListWorkspaceArtifactsResult = { items: Artifact[]; order_version?: number };

function compareByOrderKeyStable(a: Artifact, b: Artifact) {
  const ka = (a.order_key || '');
  const kb = (b.order_key || '');
  const primary = ka.localeCompare(kb);
  if (primary !== 0) return primary;

  const ta = new Date(a.created_time || 0).getTime();
  const tb = new Date(b.created_time || 0).getTime();
  if (ta !== tb) return ta - tb;

  return String(a.id || '').localeCompare(String(b.id || ''));
}

function expandToFullWorkspaceOrder(allArtifacts: Artifact[], orderedIdsIn: string[]): string[] {
  const full = [...allArtifacts]
    .sort(compareByOrderKeyStable)
    .map(c => String(c.id))
    .filter(Boolean);

  const fullSet = new Set(full);
  const orderedIds = orderedIdsIn.map(String).filter(id => fullSet.has(id));

  // If already full coverage, nothing to expand.
  if (orderedIds.length === full.length) return orderedIds;

  // Permute only the provided IDs within the existing "visible" slots.
  // This keeps all non-mentioned artifacts exactly where they are, and avoids
  // sending a partial list to the backend (which can lead to confusing results).
  const visibleSet = new Set(orderedIds);
  const it = orderedIds[Symbol.iterator]();
  const next = full.map((id) => {
    if (!visibleSet.has(id)) return id;
    const n = it.next();
    return n.done ? id : String(n.value);
  });

  // If any orderedIds weren't consumed (shouldn't happen), append them.
  const remaining = Array.from(it);
  if (remaining.length) return [...next, ...remaining.map(String)];
  return next;
}


/** A card's name for a message: its title, else its filename, else "Untitled". */
function artifactTitle(a: Artifact | undefined): string {
  if (!a) return 'Untitled';
  const ctx = safeParseArtifactContext(a.context);
  return String(ctx.title || ctx.filename || a.name || 'Untitled');
}

/** `list` with `artifact` added, unless an artifact with its id is already there. The server's
 * "created" event can arrive before the create request answers, so the same card reaches the store
 * twice; every path that adds a card goes through here. At `index` when given, else at the end. */
function withArtifact(list: Artifact[], artifact: Artifact, index?: number): Artifact[] {
  if (list.some(c => String(c.id) === String(artifact.id))) return list;
  if (typeof index !== 'number') return [...list, artifact];
  const next = [...list];
  next.splice(index, 0, artifact);
  return next;
}

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const { activeWorkspace } = useWorkspaces();

  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  // Artifacts currently shown in center panel (workspace, collection, or search results)
  const [displayedArtifacts, setDisplayedArtifacts] = useState<Artifact[]>([]);
  const [selectedArtifactIds, setSelectedArtifactIds] = useState<string[]>([]);
  const [anchorId, setAnchorId] = useState<string | null>(null);
  const [orderVersion, setOrderVersion] = useState<number | null>(null);
  const newArtifactHandlerRef = useRef<((artifact: Artifact) => void) | null>(null);

  // central loader
  const refreshArtifacts = useCallback(async (workspaceId: string) => {
    const res = await listWorkspaceArtifacts(workspaceId);
    const { items, order_version } = res as unknown as ListWorkspaceArtifactsResult;
    setArtifacts(items);
    if (typeof order_version === 'number') setOrderVersion(order_version);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!activeWorkspace?.id) {
        setArtifacts([]);
        setSelectedArtifactIds([]);
        setOrderVersion(null);
        return;
      }
      try {
        await refreshArtifacts(activeWorkspace.id);
      } catch (err) {
        if (!cancelled) {
          console.error('Failed to load artifacts', err);
          setArtifacts([]);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [activeWorkspace?.id, refreshArtifacts]);

  // Subscribe to real-time workspace change events via SSE.
  // Opens when a workspace is selected; auto-closes on workspace switch or unmount.
  useEffect(() => {
    if (!activeWorkspace?.id) return;
    const workspaceId = activeWorkspace.id;

    const unsubscribe = subscribeWorkspaceEvents(workspaceId, {
      onArtifactCreated: (artifact) => {
        setArtifacts(prev => withArtifact(prev, artifact as Artifact));
      },
      onArtifactUpdated: (artifact) => {
        setArtifacts(prev =>
          prev.map(c =>
            String(c.id) === String(artifact.id)
              ? { ...c, ...artifact } as Artifact
              : c
          )
        );
      },
      onArtifactDeleted: (artifactId) => {
        setArtifacts(prev => prev.filter(c => String(c.id) !== String(artifactId)));
        setSelectedArtifactIds(prev => prev.filter(id => id !== String(artifactId)));
      },
      onWorkspaceRefreshed: () => {
        refreshArtifacts(workspaceId);
      },
    });

    return unsubscribe;
  }, [activeWorkspace?.id, refreshArtifacts]);

  const addArtifact = useCallback(
    async (partial: Partial<Artifact>) => {
      if (!activeWorkspace?.id) return;
      const payload = {
        content: partial.content ?? '',
        context: stringifyArtifactContext(partial.context ?? { content_type: 'text/plain', preview_text: '' }),
        // Don't send collection_ids - let server default to [user_id]
      };
      try {
        const created = await addArtifactToWorkspace(activeWorkspace.id, payload);
        setArtifacts(prev => withArtifact(prev, created as Artifact));
      } catch (err) {
        console.error('Failed to create artifact', err);
      }
    },
    [activeWorkspace?.id]
  );

  // Add a pre-created artifact to local state (e.g., from upload initiation)
  const addExistingArtifact = useCallback((artifact: Artifact) => {
    setArtifacts(prev => withArtifact(prev, artifact));
  }, []);

  // Merge fields into an artifact in local state only; nothing is sent to the server. For values
  // the server owns and reports through its own route, such as upload progress (which travels
  // through PATCH /artifacts/{id}/upload-status) or the artifact that route returns.
  const patchArtifactLocally = useCallback((patchIn: Partial<Artifact>) => {
    if (patchIn.id === undefined || patchIn.id === null) return;
    setArtifacts(prev =>
      prev.map(c => (String(c.id) === String(patchIn.id) ? { ...c, ...patchIn } as Artifact : c))
    );
  }, []);

  // Create an artifact, return it, and insert it at a specific index
  const createArtifact = useCallback(
    async (partial: Partial<Artifact>, insertIndex?: number): Promise<Artifact | null> => {
      if (!activeWorkspace?.id) return null;
      
      // Compute order_key client-side for instant positioning
      let order_key: string;
      if (typeof insertIndex === 'number') {
        const before = insertIndex > 0 ? artifacts[insertIndex - 1] : null;
        const after = insertIndex < artifacts.length ? artifacts[insertIndex] : null;
        order_key = midKey(before?.order_key || null, after?.order_key || null);
      } else {
        // Append to end
        const lastArtifact = artifacts[artifacts.length - 1];
        order_key = afterKey(lastArtifact?.order_key || null);
      }

      const payload: {
        content: string;
        context: string;
        order_key: string;
        content_type?: string;
      } = {
        content: partial.content ?? '',
        context: stringifyArtifactContext(partial.context ?? { content_type: 'text/plain', preview_text: '' }),
        order_key, // Client-computed fractional index
      };
      if (partial.content_type) {
        payload.content_type = partial.content_type;
      }
      
      try {
        const created = await addArtifactToWorkspace(activeWorkspace.id, payload) as Artifact;

        // At its position, unless its "created" event already put it in the store.
        setArtifacts(prev => withArtifact(prev, created, insertIndex));

        return created;
      } catch (err) {
        console.error('Failed to create artifact', err);
        toast.error('Could not create card', {
          description: errorDetail(err, err instanceof Error ? err.message : 'Unknown error'),
        });
        return null;
      }
    },
    [activeWorkspace?.id, artifacts]
  );

  const updateArtifact = useCallback(
    async (patchIn: Partial<Artifact>): Promise<void> => {
      if (!activeWorkspace?.id) return;

      // An archived artifact is read-only: the store answers an edit to it with 404, and the
      // refresh after the failure drops it from view with the edit lost. Only restoring it is sent.
      const current = [...artifacts, ...displayedArtifacts].find(c => String(c.id) === String(patchIn.id));
      const restoring = patchIn.state === 'live';
      if (current?.state === 'archived' && !restoring
          && (typeof patchIn.context !== 'undefined' || typeof patchIn.content !== 'undefined')) {
        toast.error('This card is archived', { description: 'Restore it to edit it.' });
        return;
      }
      const archiving = patchIn.state === 'archived' && current?.state !== 'archived';
      // An edited card is no longer a new card: closing its window must never discard it.
      if (typeof patchIn.context !== 'undefined' || typeof patchIn.content !== 'undefined') {
        takeNewCard(String(patchIn.id));
      }

      // Optimistic update
      setArtifacts(prev =>
        prev.map(c =>
          String(c.id) === String(patchIn.id)
            ? { ...c, ...patchIn } as Artifact
            : c
        )
      );

      // Build minimal payload - only send fields that are explicitly set
      const payload: UpdateArtifactPayload = {};
      if (typeof patchIn.state !== 'undefined') payload.state = patchIn.state as Artifact['state'];
      if (typeof patchIn.context !== 'undefined') payload.context = stringifyArtifactContext(patchIn.context);
      if (typeof patchIn.content !== 'undefined') payload.content = patchIn.content;

      try {
        const updated = await updateWorkspaceArtifact(
          activeWorkspace.id,
          String(patchIn.id),
          payload
        );
        setArtifacts(prev =>
          prev.map(c => (String(c.id) === String(patchIn.id)
            ? { ...c, ...updated } as Artifact
            : c))
        );
        if (restoring && !current) {
          // Restored from the archived listing: the live list never held it, so read it again.
          await refreshArtifacts(activeWorkspace.id);
        }
        if (archiving) {
          // Archived artifacts leave the workspace's listing, so say where it went and offer the
          // way back while there is still something on screen to undo.
          const id = String(patchIn.id);
          toast(`Archived "${artifactTitle(current)}"`, {
            description: 'It no longer appears in this workspace.',
            action: { label: 'Undo', onClick: () => { void updateWorkspaceArtifact(activeWorkspace.id, id, { state: 'live' })
              .then(() => refreshArtifacts(activeWorkspace.id)).catch(() => {
                toast.error('Could not restore the card');
              }); } },
          });
        }
      } catch (err) {
        console.error('Failed to update artifact', err);
        toast.error(archiving ? 'Could not archive the card' : 'Could not save the card', {
          description: errorDetail(err, err instanceof Error ? err.message : 'Unknown error'),
        });
        try {
          await refreshArtifacts(activeWorkspace.id);
        } catch { /* ignore */ }
      }
    },
    [activeWorkspace?.id, artifacts, displayedArtifacts, refreshArtifacts]
  );

  const removeArtifact = useCallback(
    async (id: string) => {
      if (!activeWorkspace?.id) return;
      try {
        const workspaceId = activeWorkspace.id;
        announceRemoval(await removeWorkspaceArtifact(workspaceId, String(id)), {
          from: activeWorkspace.name || 'this workspace',
          relink: () => addArtifactToCollection(workspaceId, String(id)),
          after: () => { void refreshArtifacts(workspaceId); },
        });
        setArtifacts(prev => prev.filter(c => String(c.id) !== String(id) && String(c.root_id) !== String(id)));
        setSelectedArtifactIds(prev => prev.filter(cid => cid !== String(id)));
      } catch (err) {
        console.error('Failed to remove artifact', err);
        toast.error('Could not remove the card', {
          description: errorDetail(err, err instanceof Error ? err.message : 'Unknown error'),
        });
      }
    },
    [activeWorkspace?.id, activeWorkspace?.name, refreshArtifacts]
  );

  const dropLocally = useCallback((id: string) => {
    setArtifacts(prev => prev.filter(c => String(c.id) !== String(id) && String(c.root_id) !== String(id)));
    setSelectedArtifactIds(prev => prev.filter(cid => cid !== String(id)));
  }, []);

  // Delete as a person means it: move the artifact to Trash (`POST /artifacts/{id}/trash`), where
  // it can be restored for 30 days, as opposed to `removeArtifact`, which unlinks it from the
  // active workspace. Resolves false when the server refuses.
  const deleteArtifact = useCallback(
    async (id: string, options?: { announce?: boolean }): Promise<boolean> => {
      const current = [...artifacts, ...displayedArtifacts].find(c => String(c.id) === String(id));
      try {
        await trashArtifact(String(id));
      } catch (err) {
        console.error('Failed to move artifact to Trash', err);
        toast.error('Could not move it to Trash', {
          description: errorDetail(err, err instanceof Error ? err.message : 'Unknown error'),
        });
        return false;
      }
      dropLocally(id);
      if (options?.announce !== false) {
        const workspaceId = activeWorkspace?.id;
        toast(`Moved "${artifactTitle(current)}" to Trash`, {
          description: `Restore it from Trash within ${TRASH_RETENTION_DAYS} days.`,
          action: { label: 'Undo', onClick: () => {
            void updateWorkspaceArtifact(workspaceId ?? '', String(id), { state: 'live' })
              .then(() => (workspaceId ? refreshArtifacts(workspaceId) : undefined))
              .catch(() => { toast.error('Could not restore the card'); });
          } },
          cancel: { label: 'View Trash', onClick: () => { window.dispatchEvent(new Event(OPEN_TRASH_EVENT)); } },
        });
      }
      return true;
    },
    [activeWorkspace?.id, artifacts, displayedArtifacts, dropLocally, refreshArtifacts]
  );

  // Delete for good (`DELETE /artifacts/{id}`): emptying Trash, and discarding a new card that was
  // closed untouched, which never held anything to restore. Resolves false when the server refuses.
  const discardArtifact = useCallback(
    async (id: string): Promise<boolean> => {
      try {
        await deleteWorkspaceArtifact(activeWorkspace?.id ?? '', String(id));
      } catch (err) {
        console.error('Failed to delete artifact', err);
        toast.error('Could not delete', {
          description: errorDetail(err, err instanceof Error ? err.message : 'Unknown error'),
        });
        return false;
      }
      dropLocally(id);
      return true;
    },
    [activeWorkspace?.id, dropLocally]
  );


  const orderArtifacts = useCallback(
    async (orderedIds: string[]) => {
      if (!activeWorkspace?.id) return;

      // Ensure we always persist a full-workspace ordering.
      // Some UIs can call this with only the currently-visible IDs (e.g., filtered/search).
      const orderedIdsFull = expandToFullWorkspaceOrder(artifacts, orderedIds);

      // Optimistic update: reorder the artifacts array immediately
      setArtifacts(prev => {
        const applyIds = expandToFullWorkspaceOrder(prev, orderedIdsFull);
        const byId = new Map(prev.map(c => [String(c.id), c]));
        const nextUnkeyed: Artifact[] = [];
        for (const id of applyIds) {
          const c = byId.get(String(id));
          if (c) nextUnkeyed.push(c);
        }
        // Include any artifacts not in orderedIds at the end
        for (const c of prev) {
          if (!applyIds.includes(String(c.id))) nextUnkeyed.push(c);
        }

        // Browser "manual" sorting uses order_key. The backend /order endpoint returns
        // only {version}, not updated keys, so order_key is updated locally to keep the
        // UI responsive and deterministic.
        let prevKey: string | null = null;
        const next = nextUnkeyed.map((c) => {
          const nextKey = afterKey(prevKey);
          prevKey = nextKey;
          return { ...c, order_key: nextKey };
        });

        return next;
      });

      // Use bulk /order endpoint - server computes new order_keys
      try {
        const res = await orderWorkspaceArtifacts(
          activeWorkspace.id,
          orderedIdsFull,
          orderVersion ?? undefined
        );
        if (typeof res?.version === 'number') setOrderVersion(res.version);
      } catch (err: unknown) {
        console.error('[ORDER] Error:', err);
        // On error, refetch to recover correct state
        const fresh = await listWorkspaceArtifacts(activeWorkspace.id) as unknown as ListWorkspaceArtifactsResult;
        setArtifacts(fresh.items);
        if (typeof fresh.order_version === 'number') setOrderVersion(fresh.order_version);
        toast.error('Could not save order');
      }
    },
    [activeWorkspace?.id, orderVersion, artifacts]
  );

  const importArtifactsByRootIds = useCallback(
    async (rootIdsIn: string[], insertIndex: number) => {
      if (!activeWorkspace?.id) return;

      const rootIds = rootIdsIn.map(String).map(v => v.trim()).filter(Boolean);
      if (rootIds.length === 0) return;

      const workspaceId = activeWorkspace.id;

      // Import sequentially to preserve user drag order and avoid noisy parallel errors
      for (const rootId of rootIds) {
        try {
          await importCollectionArtifactToWorkspace(workspaceId, rootId);
        } catch {
          // Ignore: not readable / already exists / etc
        }
      }

      // Fetch authoritative artifacts list + version, then compute the new ordering
      let fresh: ListWorkspaceArtifactsResult;
      try {
        const res = await listWorkspaceArtifacts(workspaceId);
        fresh = res as unknown as ListWorkspaceArtifactsResult;
      } catch (err) {
        console.error('Failed to refresh artifacts after import', err);
        return;
      }

      const normalized = fresh.items ?? [];
      if (typeof fresh.order_version === 'number') setOrderVersion(fresh.order_version);

      // Determine which workspace artifact IDs correspond to the dropped root IDs
      const idsToInsert = rootIds
        .map((rid) => normalized.find((c) => String(c.root_id || '') === rid)?.id)
        .filter((v): v is NonNullable<typeof v> => v != null)
        .map(String)
        .filter(Boolean);

      // If nothing new was inserted, just sync to fresh state
      if (idsToInsert.length === 0) {
        setArtifacts(normalized);
        return;
      }

      const sorted = [...normalized].sort(compareByOrderKeyStable);
      const currentOrder = sorted.map((c) => String(c.id)).filter(Boolean);
      const remaining = currentOrder.filter((id) => !idsToInsert.includes(id));

      const clampedIndex = Math.max(0, Math.min(insertIndex, remaining.length));
      const nextOrder = [
        ...remaining.slice(0, clampedIndex),
        ...idsToInsert,
        ...remaining.slice(clampedIndex),
      ];

      // Optimistically update local ordering + order_key for responsive UI
      const byId = new Map(sorted.map((c) => [String(c.id), c] as const));
      let prevKey: string | null = null;
      const nextArtifacts: Artifact[] = [];

      for (const id of nextOrder) {
        const artifact = byId.get(String(id));
        if (!artifact) continue;
        const nextKey = afterKey(prevKey);
        prevKey = nextKey;
        nextArtifacts.push({ ...artifact, order_key: nextKey });
      }

      // Include any artifacts not covered (shouldn't happen) at the end
      for (const artifact of sorted) {
        const id = String(artifact.id);
        if (!id || nextOrder.includes(id)) continue;
        const nextKey = afterKey(prevKey);
        prevKey = nextKey;
        nextArtifacts.push({ ...artifact, order_key: nextKey });
      }

      setArtifacts(nextArtifacts);

      // Persist ordering server-side
      try {
        const res = await orderWorkspaceArtifacts(
          workspaceId,
          nextOrder,
          typeof fresh.order_version === 'number' ? fresh.order_version : orderVersion ?? undefined
        );
        if (typeof res?.version === 'number') setOrderVersion(res.version);
      } catch (err) {
        console.error('Failed to save order after import', err);
        try {
          await refreshArtifacts(workspaceId);
        } catch {
          // ignore
        }
      }
    },
    [activeWorkspace?.id, orderVersion, refreshArtifacts]
  );

  // selection
  const clearSelection = useCallback(() => {
    setSelectedArtifactIds([]);
    setAnchorId(null);
  }, []);

  const selectAllArtifacts = useCallback(() => {
    setSelectedArtifactIds(artifacts.map(c => String(c.id)));
  }, [artifacts]);

  const selectArtifact = useCallback(
    (id: string, event: MouseEvent) => {
      const isShift = event.shiftKey;
      const isMeta = event.metaKey || event.ctrlKey;

      setSelectedArtifactIds(prev => {
        if (isShift && anchorId) {
          const ids = artifacts.map(c => String(c.id));
          const start = ids.indexOf(anchorId);
          const end = ids.indexOf(id);
          if (start === -1 || end === -1) return prev;
          const [lo, hi] = start < end ? [start, end] : [end, start];
          const range = ids.slice(lo, hi + 1);
          return Array.from(new Set([...prev, ...range]));
        }

        if (isMeta) {
          setAnchorId(id);
          return prev.includes(id) ? prev.filter(cid => cid !== id) : [...prev, id];
        }

        setAnchorId(id);
        return [id];
      });

      if (!isShift) setAnchorId(id);
    },
    [anchorId, artifacts]
  );

  const createNewArtifact = useCallback(() => {
    const placeholder: Artifact = {
      content: '',
      context: JSON.stringify({ content_type: 'text/plain', preview_text: '' }),
      state: 'live',
    };
    newArtifactHandlerRef.current?.(placeholder);
  }, []);

  const registerNewArtifactHandler = useCallback((fn: (artifact: Artifact) => void) => {
    newArtifactHandlerRef.current = fn;
  }, []);

  const extractInformationFromArtifact = useCallback(
    async (sourceArtifactId: string, contextArtifactIds?: string[]) => {
      if (!activeWorkspace?.id) return;
      if (!sourceArtifactId) return;

      try {
        const result = await extractInformation(activeWorkspace.id, sourceArtifactId, contextArtifactIds);

        await refreshArtifacts(activeWorkspace.id);

        const created = Array.isArray(result.created_artifact_ids) ? result.created_artifact_ids.length : 0;
        if (result.warning) {
          toast.warning(result.warning);
        } else {
          toast.success(`Extracted ${created} note${created === 1 ? '' : 's'}`);
        }
      } catch (err) {
        console.error('Failed to extract information', err);
        toast.error('Extract failed');
      }
    },
    [activeWorkspace?.id, refreshArtifacts]
  );

  const extractInformationFromSelection = useCallback(
    async (options?: { sourceArtifactId?: string }) => {
      if (!activeWorkspace?.id) return;

      const forcedSourceId = options?.sourceArtifactId ? String(options.sourceArtifactId) : null;
      const selectedIds = selectedArtifactIds.map(String);

      const sourceId = forcedSourceId || anchorId || selectedIds[0] || null;
      if (!sourceId) {
        toast.error('Select one or more cards to extract from');
        return;
      }

      const artifactIds = selectedIds.filter((id) => id !== sourceId);
      await extractInformationFromArtifact(sourceId, artifactIds);
    },
    [activeWorkspace?.id, selectedArtifactIds, anchorId, extractInformationFromArtifact]
  );

  const value = useMemo(
    () => ({
      artifacts,
      displayedArtifacts,
      setDisplayedArtifacts,
      selectedArtifactIds,
      addArtifact,
      addExistingArtifact,
      patchArtifactLocally,
      createArtifact,
      updateArtifact,
      removeArtifact,
      deleteArtifact,
      discardArtifact,
      orderArtifacts,
      importArtifactsByRootIds,
      refreshArtifacts,
      selectArtifact,
      selectAllArtifacts,
      unselectAllArtifacts: clearSelection,
      createNewArtifact,
      extractInformationFromArtifact,
      extractInformationFromSelection,
      registerNewArtifactHandler,
    }),
    [
      artifacts,
      displayedArtifacts,
      selectedArtifactIds,
      addArtifact,
      addExistingArtifact,
      patchArtifactLocally,
      createArtifact,
      updateArtifact,
      removeArtifact,
      deleteArtifact,
      discardArtifact,
      orderArtifacts,
      importArtifactsByRootIds,
      refreshArtifacts,
      selectArtifact,
      selectAllArtifacts,
      clearSelection,
      createNewArtifact,
      extractInformationFromArtifact,
      extractInformationFromSelection,
      registerNewArtifactHandler,
    ]
  );

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}
