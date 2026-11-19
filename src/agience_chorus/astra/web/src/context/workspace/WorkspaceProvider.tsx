// context/workspace/WorkspaceProvider.tsx
import {
  useState, useEffect, useCallback, useContext, useMemo, useRef, ReactNode, MouseEvent,
} from 'react';
import {
  listWorkspaceArtifacts,
  addArtifactToWorkspace,
  importCollectionArtifactToWorkspace,
  updateWorkspaceArtifact,
  removeWorkspaceArtifact,
  deleteWorkspaceArtifact,
  moveWorkspaceArtifacts,
  subscribeWorkspaceEvents,
} from '../../api/workspaces';
import { WorkspaceContext } from './WorkspaceContext';
import { ConfirmContext } from '@/context/dialog/ConfirmContext';
import { showIssued, takeIssued } from './issuedToken';
import { Artifact } from './workspace.types';
import { useWorkspaces } from '../workspaces/WorkspacesContext';
import { toast } from 'sonner';
import { safeParseArtifactContext, stringifyArtifactContext } from '@/utils/artifactContext';
import { extractInformation } from '../../api/agent';
import { errorDetail, refusedWriteDetail } from '../../utils/errorDetail';
import { announceRemoval } from '../../utils/removal';
import { addArtifactToCollection } from '../../api/collections';
import { trashArtifact, untrashArtifact } from '../../api/artifacts';
import { COLLECTION_CONTENT_TYPE, WORKSPACE_CONTENT_TYPE } from '../../utils/content-type';
import { OPEN_TRASH_EVENT, TRASH_RETENTION_DAYS, announceArtifactChange } from '../../constants/strings';
import { keyList, keyedIn, keyedNotIn, moveGroup, toggle, unique, without, withoutKey } from '@/display-state/lists';

type UpdateArtifactPayload = {
  state?: Artifact['state'];
  context?: string;
  content?: string;
};

type ListWorkspaceArtifactsResult = { items: Artifact[]; order_version?: number };

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
  // The app's dialogs (the remove choice below); absent only where a test renders this alone.
  const dialog = useContext(ConfirmContext);
  const { activeWorkspace } = useWorkspaces();

  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const artifactsRef = useRef<Artifact[]>([]);
  artifactsRef.current = artifacts;
  // Artifacts currently shown in center panel (workspace, collection, or search results)
  const [displayedArtifacts, setDisplayedArtifacts] = useState<Artifact[]>([]);
  // Opened from outside the active list. 2026-10-23, a tester: a note whose only home is a
  // workspace shown in a window could not be edited there, and its editor vanished while typing —
  // editability asked whether it was in the active tab, and the window read it from the list the
  // center panel replaces on every change.
  const [openedArtifacts, setOpenedArtifacts] = useState<Artifact[]>([]);
  const [selectedArtifactIds, setSelectedArtifactIds] = useState<string[]>([]);
  const [anchorId, setAnchorId] = useState<string | null>(null);
  const [orderVersion, setOrderVersion] = useState<number | null>(null);
  const newArtifactHandlerRef = useRef<((artifact: Artifact) => void) | null>(null);

  // The workspace on screen now, read when an answer arrives: a list fetched for another one is
  // dropped rather than shown under this one's tab.
  const activeIdRef = useRef<string | undefined>(activeWorkspace?.id);
  activeIdRef.current = activeWorkspace?.id;

  // central loader
  const refreshArtifacts = useCallback(async (workspaceId: string) => {
    const res = await listWorkspaceArtifacts(workspaceId);
    if (String(activeIdRef.current ?? '') !== String(workspaceId)) return;
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
        // Applied only while this workspace is still the active one. 2026-10-19, on staging: a tab
        // opened while the previous workspace was loading showed the previous workspace's cards,
        // because its answer arrived after the switch and replaced the new one's.
        const res = await listWorkspaceArtifacts(activeWorkspace.id);
        if (cancelled) return;
        const { items, order_version } = res as unknown as ListWorkspaceArtifactsResult;
        setArtifacts(items);
        if (typeof order_version === 'number') setOrderVersion(order_version);
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
        // A member this list does not hold that is live again (restored elsewhere) is read in, at
        // its place. 2026-10-29, a tester: a card restored with the Inbox open appeared only
        // after a refresh.
        const held = artifactsRef.current.some(c => String(c.id) === String(artifact.id));
        if (!held && artifact.state === 'live') {
          void refreshArtifacts(workspaceId);
          return;
        }
        setArtifacts(prev =>
          prev.map(c =>
            String(c.id) === String(artifact.id)
              ? { ...c, ...artifact } as Artifact
              : c
          )
        );
      },
      onArtifactDeleted: (artifactId) => {
        setArtifacts(prev => withoutKey(prev, c => c.id, artifactId));
        setSelectedArtifactIds(prev => without(prev, String(artifactId)));
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
        const { record: created, issued } = takeIssued(await addArtifactToWorkspace(activeWorkspace.id, payload) as Artifact);
        await showIssued(dialog, issued);
        setArtifacts(prev => withArtifact(prev, created));
      } catch (err) {
        // Said, with the server's reason, as `createArtifact` says it (BUG-061, 2026-11-10: a
        // refused create left nothing on screen, its 503 only in the console).
        console.error('Failed to create artifact', err);
        toast.error('Could not create the artifact', {
          description: refusedWriteDetail(err, err instanceof Error ? err.message : 'Unknown error'),
        });
      }
    },
    [activeWorkspace?.id, dialog]
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
    const patch = (prev: Artifact[]) =>
      prev.map(c => (String(c.id) === String(patchIn.id) ? { ...c, ...patchIn } as Artifact : c));
    setArtifacts(patch);
    setOpenedArtifacts(patch);
  }, []);

  // A copy opened again from a list that has not caught up is older than the one kept: the newer
  // stays. 2026-10-27, measured in a browser: a note edited in its window and opened again from its
  // workspace's window showed its old title and an empty body.
  const keepOpenedArtifact = useCallback((artifact: Artifact) => {
    if (artifact.id === undefined || artifact.id === null) return;
    setOpenedArtifacts(prev => {
      const kept = prev.find(c => String(c.id) === String(artifact.id));
      const newer = kept && String(kept.modified_time ?? '') > String(artifact.modified_time ?? '') ? kept : artifact;
      return [...withoutKey(prev, c => c.id, artifact.id), newer];
    });
  }, []);

  const isEditable = useCallback((artifact: Artifact | null | undefined) => {
    if (!artifact || artifact.state === 'archived') return false;
    const id = String(artifact.id);
    return artifacts.some(c => String(c.id) === id) || openedArtifacts.some(c => String(c.id) === id);
  }, [artifacts, openedArtifacts]);

  // Create an artifact, return it, and insert it at a specific index
  const createArtifact = useCallback(
    async (partial: Partial<Artifact>, insertIndex?: number): Promise<Artifact | null> => {
      if (!activeWorkspace?.id) return null;
      
      // Mantle computes the order key: just before the member at insertIndex, or at the end.
      const beforeId = typeof insertIndex === 'number' ? artifacts[insertIndex]?.id : undefined;
      const payload: {
        content: string;
        context: string;
        before_id?: string;
        content_type?: string;
      } = {
        content: partial.content ?? '',
        context: stringifyArtifactContext(partial.context ?? { content_type: 'text/plain', preview_text: '' }),
        ...(beforeId ? { before_id: String(beforeId) } : {}),
      };
      if (partial.content_type) {
        payload.content_type = partial.content_type;
      }
      
      try {
        // A token the create issued is shown once and kept out of everything below.
        const { record: created, issued } = takeIssued(
          await addArtifactToWorkspace(activeWorkspace.id, payload) as Artifact,
        );
        await showIssued(dialog, issued);

        // At its position, unless its "created" event already put it in the store.
        setArtifacts(prev => withArtifact(prev, created, insertIndex));
        // A new workspace or collection joins the lists of them (tabs, Ctrl+K, pickers).
        const createdType = created.content_type ?? safeParseArtifactContext(created.context).content_type;
        if (createdType === WORKSPACE_CONTENT_TYPE || createdType === COLLECTION_CONTENT_TYPE) {
          announceArtifactChange({ ...created, id: String(created.id) });
        }

        return created;
      } catch (err) {
        console.error('Failed to create artifact', err);
        toast.error('Could not create the artifact', {
          description: refusedWriteDetail(err, err instanceof Error ? err.message : 'Unknown error'),
        });
        return null;
      }
    },
    [activeWorkspace?.id, artifacts, dialog]
  );

  const updateArtifact = useCallback(
    async (patchIn: Partial<Artifact>): Promise<boolean> => {
      if (!activeWorkspace?.id) return false;

      // An archived artifact is read-only: the store answers an edit to it with 404, and the
      // refresh after the failure drops it from view with the edit lost. Only restoring it is sent.
      const current = [...artifacts, ...openedArtifacts, ...displayedArtifacts].find(c => String(c.id) === String(patchIn.id));
      const restoring = patchIn.state === 'live';
      if (current?.state === 'archived' && !restoring
          && (typeof patchIn.context !== 'undefined' || typeof patchIn.content !== 'undefined')) {
        toast.error('This artifact is archived', { description: 'Restore it to edit it.' });
        return false;
      }
      const archiving = patchIn.state === 'archived' && current?.state !== 'archived';
      // Optimistic update
      const optimistic = (prev: Artifact[]) =>
        prev.map(c =>
          String(c.id) === String(patchIn.id)
            ? { ...c, ...patchIn } as Artifact
            : c
        );
      setArtifacts(optimistic);
      setOpenedArtifacts(optimistic);

      // Build minimal payload - only send fields that are explicitly set
      const payload: UpdateArtifactPayload = {};
      if (typeof patchIn.state !== 'undefined') payload.state = patchIn.state as Artifact['state'];
      if (typeof patchIn.context !== 'undefined') payload.context = stringifyArtifactContext(patchIn.context);
      if (typeof patchIn.content !== 'undefined') payload.content = patchIn.content;

      try {
        // An update that issues a Key's token answers it once: shown, then kept out of the store.
        const { record: updated, issued } = takeIssued(await updateWorkspaceArtifact(
          activeWorkspace.id,
          String(patchIn.id),
          payload
        ));
        await showIssued(dialog, issued);
        const confirmed = (prev: Artifact[]) =>
          prev.map(c => (String(c.id) === String(patchIn.id)
            ? { ...c, ...updated } as Artifact
            : c));
        setArtifacts(confirmed);
        setOpenedArtifacts(confirmed);
        announceArtifactChange({ ...updated, id: String(patchIn.id) });
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
              .then(() => { announceArtifactChange({ id, state: 'live' }); return refreshArtifacts(activeWorkspace.id); }).catch(() => {
                toast.error('Could not restore the artifact');
              }); } },
          });
        }
        return true;
      } catch (err) {
        console.error('Failed to update artifact', err);
        toast.error(archiving ? 'Could not archive the artifact' : 'Could not save the artifact', {
          description: current
            ? refusedWriteDetail(err, err instanceof Error ? err.message : 'Unknown error')
            : errorDetail(err, err instanceof Error ? err.message : 'Unknown error'),
        });
        try {
          await refreshArtifacts(activeWorkspace.id);
        } catch { /* ignore */ }
        return false;
      }
    },
    [activeWorkspace?.id, artifacts, openedArtifacts, displayedArtifacts, refreshArtifacts, dialog]
  );


  const dropLocally = useCallback((id: string) => {
    setArtifacts(prev => withoutKey(withoutKey(prev, c => c.id, id), c => c.root_id, id));
    setSelectedArtifactIds(prev => without(prev, String(id)));
  }, []);

  // What a move to Trash says, from any entry point: what moved, Undo, and View Trash. 2026-10-23,
  // a tester: the toolbar's Delete said it in text alone, the card menu's offered both buttons.
  const announceTrashed = useCallback((ids: string[], what: string) => {
    const workspaceId = activeWorkspace?.id;
    toast(`Moved ${what} to Trash`, {
      description: `Restore ${ids.length === 1 ? 'it' : 'them'} from Trash within ${TRASH_RETENTION_DAYS} days.`,
      action: { label: 'Undo', onClick: () => {
        void Promise.all(ids.map((id) => untrashArtifact(id)))
          .then(() => (workspaceId ? refreshArtifacts(workspaceId) : undefined))
          .catch(() => { toast.error(ids.length === 1 ? 'Could not restore the artifact' : 'Could not restore every artifact'); });
      } },
      cancel: { label: 'View Trash', onClick: () => { window.dispatchEvent(new Event(OPEN_TRASH_EVENT)); } },
    });
  }, [activeWorkspace?.id, refreshArtifacts]);

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
      if (options?.announce !== false) announceTrashed([String(id)], `"${artifactTitle(current)}"`);
      return true;
    },
    [artifacts, displayedArtifacts, dropLocally, announceTrashed]
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
        setArtifacts(prev => withoutKey(withoutKey(prev, c => c.id, id), c => c.root_id, id));
        setSelectedArtifactIds(prev => without(prev, String(id)));
      } catch (err) {
        // Made here and shown elsewhere too: Mantle keeps it here (its content is keyed to this
        // workspace) and says so, and the person chooses. 2026-11-15, the Tester: the 409 was not
        // shown at all.
        if ((err as { response?: { status?: number } })?.response?.status === 409) {
          if (!dialog) {
            toast.error('Could not remove the artifact', { description: errorDetail(err, '') });
            return;
          }
          const everywhere = await dialog.confirm({
            title: 'This was made here',
            description: `${errorDetail(err, '')} Removing it everywhere moves it to Trash, where it can be restored within ${TRASH_RETENTION_DAYS} days.`,
            confirmLabel: 'Remove it everywhere',
            cancelLabel: 'Keep it here',
            tone: 'warn',
          });
          if (everywhere) await deleteArtifact(String(id));
          return;
        }
        console.error('Failed to remove artifact', err);
        toast.error('Could not remove the artifact', {
          description: errorDetail(err, err instanceof Error ? err.message : 'Unknown error'),
        });
      }
    },
    [activeWorkspace?.id, activeWorkspace?.name, deleteArtifact, dialog, refreshArtifacts]
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


  const moveArtifacts = useCallback(
    async (ids: string[], beforeId: string | null) => {
      if (!activeWorkspace?.id || ids.length === 0) return;

      // Shown at once; Mantle places them and answers the order's new version.
      setArtifacts(prev => {
        const idOf = (c: Artifact) => String(c.id);
        const stay = keyedNotIn(prev, idOf, ids);
        const at = beforeId ? stay.findIndex(c => idOf(c) === beforeId) : -1;
        return moveGroup(prev, keyedIn(prev, idOf, ids), at === -1 ? stay.length : at);
      });

      try {
        const res = await moveWorkspaceArtifacts(activeWorkspace.id, ids, beforeId, orderVersion ?? undefined);
        if (typeof res?.version === 'number') setOrderVersion(res.version);
      } catch (err: unknown) {
        console.error('[ORDER] Error:', err);
        const fresh = await listWorkspaceArtifacts(activeWorkspace.id) as unknown as ListWorkspaceArtifactsResult;
        setArtifacts(fresh.items);
        if (typeof fresh.order_version === 'number') setOrderVersion(fresh.order_version);
        toast.error('Could not save order');
      }
    },
    [activeWorkspace?.id, orderVersion]
  );

  const importArtifactsByRootIds = useCallback(
    async (rootIdsIn: string[], insertIndex: number) => {
      if (!activeWorkspace?.id) return;

      const rootIds = keyList(rootIdsIn);
      if (rootIds.length === 0) return;

      const workspaceId = activeWorkspace.id;

      // Each lands just before the member at insertIndex; Mantle computes the order key.
      // Sequential, so the dropped order holds.
      const beforeId = artifacts[insertIndex]?.id;
      for (const rootId of rootIds) {
        try {
          await importCollectionArtifactToWorkspace(workspaceId, rootId, beforeId ? String(beforeId) : undefined);
        } catch {
          // Ignore: not readable / already exists / etc
        }
      }

      try {
        await refreshArtifacts(workspaceId);
      } catch (err) {
        console.error('Failed to refresh artifacts after import', err);
      }
    },
    [activeWorkspace?.id, artifacts, refreshArtifacts]
  );

  // selection
  const clearSelection = useCallback(() => {
    setSelectedArtifactIds([]);
    setAnchorId(null);
  }, []);

  const selectAllArtifacts = useCallback(() => {
    setSelectedArtifactIds(artifacts.map(c => String(c.id)));
  }, [artifacts]);

  // `shownIds` is the order the caller displays. A shift-click range runs over what the person sees;
  // the provider's own list is in another order and holds artifacts the view filters out (2026-10-31,
  // a tester: Shift between two adjacent cards selected eight scattered ones, and in the archived view
  // fifteen with no visible borders).
  const selectArtifact = useCallback(
    (id: string, event: MouseEvent, shownIds?: string[]) => {
      const isShift = event.shiftKey;
      const isMeta = event.metaKey || event.ctrlKey;

      // A right-click opens the artifact's menu on the selection it belongs to, and selects it alone
      // when it belongs to none. 2026-10-29, on staging: the right-click collapsed three selected
      // artifacts to one, and the menu's Delete moved only that one to Trash.
      if (event.button === 2) {
        setSelectedArtifactIds(prev => (prev.includes(id) ? prev : [id]));
        if (!isShift) setAnchorId(id);
        return;
      }

      setSelectedArtifactIds(prev => {
        if (isShift && anchorId) {
          const ids = shownIds ?? artifacts.map(c => String(c.id));
          const start = ids.indexOf(anchorId);
          const end = ids.indexOf(id);
          if (start === -1 || end === -1) return prev;
          const [lo, hi] = start < end ? [start, end] : [end, start];
          const range = ids.slice(lo, hi + 1);
          return unique([...prev, ...range]);
        }

        if (isMeta) {
          setAnchorId(id);
          return toggle(prev, id);
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
        toast.error('Select one or more artifacts to extract from');
        return;
      }

      const artifactIds = without(selectedIds, sourceId);
      await extractInformationFromArtifact(sourceId, artifactIds);
    },
    [activeWorkspace?.id, selectedArtifactIds, anchorId, extractInformationFromArtifact]
  );

  const value = useMemo(
    () => ({
      artifacts,
      displayedArtifacts,
      setDisplayedArtifacts,
      openedArtifacts,
      keepOpenedArtifact,
      isEditable,
      selectedArtifactIds,
      addArtifact,
      addExistingArtifact,
      patchArtifactLocally,
      createArtifact,
      updateArtifact,
      removeArtifact,
      deleteArtifact,
      announceTrashed,
      discardArtifact,
      moveArtifacts,
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
      openedArtifacts,
      keepOpenedArtifact,
      isEditable,
      selectedArtifactIds,
      addArtifact,
      addExistingArtifact,
      patchArtifactLocally,
      createArtifact,
      updateArtifact,
      removeArtifact,
      deleteArtifact,
      announceTrashed,
      discardArtifact,
      moveArtifacts,
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
