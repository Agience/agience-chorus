import { ReactNode, useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { toast } from 'sonner';
import {
  listWorkspaces,
  createWorkspace as apiCreateWorkspace,
  updateWorkspace as apiUpdateWorkspace,
  subscribeAccessChanges,
} from '../../api/workspaces';
import { trashArtifact, untrashArtifact } from '../../api/artifacts';
import { WorkspacesContext, WorkspacesContextType } from './WorkspacesContext';
import { Workspace } from '../workspace/workspace.types';
import { WorkspaceUpdate } from '../../api/types/workspace';
import { useAuth } from '../../hooks/useAuth';
import { usePreferences } from '../../hooks/usePreferences';
import { errorDetail } from '../../utils/errorDetail';
import { inboxWorkspaceId } from '../../utils/inbox';
import { safeParseArtifactContext, stringifyArtifactContext } from '../../utils/artifactContext';
import { WORKSPACE_CONTENT_TYPE } from '../../utils/content-type';
import { ARTIFACT_CHANGED_EVENT, changeOf } from '../../constants/strings';
import { openLinkedArtifact, readLinkedArtifact } from '../../utils/linkedArtifact';
import { keyList, keyedIn, withoutKey } from '@/display-state/lists';

// The tab a person last selected, kept per browser and account so a reload reopens it. A
// convenience only: unreadable storage falls back to the Inbox.
const lastTabKey = (userId: string) => `agience.lastWorkspaceTab.${userId}`;

function readLastTab(userId: string | undefined): string | null {
  if (!userId) return null;
  try { return localStorage.getItem(lastTabKey(userId)); } catch { return null; }
}

function writeLastTab(userId: string | undefined, id: string | null): void {
  if (!userId || !id) return;
  try { localStorage.setItem(lastTabKey(userId), id); } catch { /* storage unavailable */ }
}

// The first list read is tried three times, waiting 1 s and then 2 s between tries.
const FIRST_LIST_TRIES = 3;
const FIRST_LIST_BACKOFF_MS = 1000;

export function WorkspacesProvider({ children }: { children: ReactNode }) {
  const { isAuthenticated, loading, user } = useAuth();
  const { preferences, isLoading: preferencesLoading, updatePreferences } = usePreferences();
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [activeWorkspaceId, setActiveWorkspaceId] = useState<string | null>(null);

  const dockedWorkspaceTabIds = useMemo(() => {
    const raw = preferences.browser?.dockedWorkspaceCardIds;
    return Array.isArray(raw) ? keyList(raw) : undefined;
  }, [preferences.browser?.dockedWorkspaceCardIds]);

  // Deep link: read artifactId from URL path and workspace from query param.
  const { artifactId: urlArtifactId } = useParams<{ artifactId?: string }>();
  const [searchParams] = useSearchParams();
  const urlWorkspaceId = searchParams.get('workspace');
  const deepLinkApplied = useRef(false);
  // A workspace being opened as a tab before the preference that docks it has come back. The
  // selection below keeps it rather than falling back to a docked tab in the meantime.
  const opening = useRef<string | null>(null);

  // Several reads of the list can be in flight at once (the first load, a change announced on the
  // event stream, a deep link). Only the newest read is kept: an older one that answers last holds
  // a list from before the change, and keeping it would drop what the newer read found. A change
  // made here (create, delete) also retires the reads already in flight.
  // Any read that loads the list clears the error left by a failed first load.
  const [listError, setListError] = useState<string | null>(null);
  const listSeq = useRef(0);
  const readList = useCallback(async (): Promise<Workspace[] | null> => {
    const n = ++listSeq.current;
    const data = await listWorkspaces();
    if (n !== listSeq.current) return null;
    const list = Array.isArray(data) ? data : [];
    setWorkspaces(list);
    setListError(null);
    return list;
  }, []);

  // Load workspaces once authenticated. A read that fails is tried again after 1 s and then 2 s,
  // since a service that is slow to answer leaves the session with no workspace and no way to make
  // anything. When all three fail, the error stays on screen with Retry until a read succeeds.
  const [loadAttempt, setLoadAttempt] = useState(0);
  useEffect(() => {
    if (loading || !isAuthenticated) return;
    let live = true;
    (async () => {
      let last: unknown;
      for (let i = 0; i < FIRST_LIST_TRIES; i++) {
        if (i > 0) await new Promise(r => setTimeout(r, FIRST_LIST_BACKOFF_MS * 2 ** (i - 1)));
        if (!live) return;
        try {
          await readList();
          if (live) setListError(null);
          return;
        } catch (err) {
          last = err;
        }
      }
      if (!live) return;
      console.error('Failed to load workspaces', last);
      const description = errorDetail(last, last instanceof Error ? last.message : 'Unknown error');
      toast.error('Could not load workspaces', { description });
      setListError(description);
    })();
    return () => { live = false; };
  }, [isAuthenticated, loading, readList, loadAttempt]);

  // A workspace saved or created anywhere in the app is read again, so its name and its place in
  // every list (tabs, Ctrl+K, Open as tab) follow without a reload. 2026-10-29, a tester: a
  // workspace made as a card could not be opened as a tab or found with Ctrl+K until a refresh.
  const listedRef = useRef<Workspace[]>([]);
  listedRef.current = workspaces;
  useEffect(() => {
    if (loading || !isAuthenticated) return;
    const onChange = (e: Event) => {
      const change = changeOf(e);
      if (!change) return;
      const type = (change.content_type as string | undefined) ?? safeParseArtifactContext(change.context).content_type;
      if (type !== WORKSPACE_CONTENT_TYPE && !listedRef.current.some(w => w.id === change.id)) return;
      readList().catch(err => console.error('Failed to reload workspaces', err));
    };
    window.addEventListener(ARTIFACT_CHANGED_EVENT, onChange);
    return () => window.removeEventListener(ARTIFACT_CHANGED_EVENT, onChange);
  }, [isAuthenticated, loading, readList]);

  // A grant applied at Mantle (a claimed invitation, a share) can add a workspace to this
  // account's list. Mantle announces it on the item, so the list is read again when one arrives.
  useEffect(() => {
    if (loading || !isAuthenticated) return;
    return subscribeAccessChanges(() => {
      readList().catch(err => console.error('Failed to reload workspaces', err));
    });
  }, [isAuthenticated, loading, readList]);

  useEffect(() => {
    if (loading || !isAuthenticated || preferencesLoading) return;

    if (workspaces.length === 0) {
      setActiveWorkspaceId(null);
      return;
    }

    const visibleWorkspaces = dockedWorkspaceTabIds
      ? keyedIn(workspaces, (workspace) => workspace.id, dockedWorkspaceTabIds)
      : workspaces;

    if (visibleWorkspaces.length === 0) {
      // No workspaces are visible - show empty dock state
      setActiveWorkspaceId(null);
      return;
    }

    const isVisible = (id: string | null | undefined) =>
      Boolean(id && visibleWorkspaces.some((workspace) => workspace.id === id));
    if (opening.current && dockedWorkspaceTabIds?.includes(opening.current)) opening.current = null;
    setActiveWorkspaceId((current) => {
      if (current && current === opening.current && workspaces.some((w) => w.id === current)) return current;
      if (isVisible(current)) return current;
      // On load: the tab last selected here, else the Inbox, else the first tab. 2026-10-23, a
      // tester: a reload selected the workspace whose id sorts first, not the Inbox they had open.
      const last = readLastTab(user?.id);
      if (isVisible(last)) return last;
      const inbox = inboxWorkspaceId(visibleWorkspaces);
      if (isVisible(inbox)) return inbox;
      return visibleWorkspaces[0]?.id || null;
    });
  }, [dockedWorkspaceTabIds, isAuthenticated, loading, preferencesLoading, workspaces, user?.id, updatePreferences, preferences.browser]);

  useEffect(() => {
    writeLastTab(user?.id, activeWorkspaceId);
  }, [activeWorkspaceId, user?.id]);

  // The route names the open workspace. A tab click, the selection on load, a create or a close
  // changes `activeWorkspaceId` alone, and the Share dialog takes the item it shares from the
  // route (review 14), so the route follows. Not while a link in the route is still being
  // resolved: the deep-link effect below opens it, or says it cannot.
  const navigate = useNavigate();
  useEffect(() => {
    if (!activeWorkspaceId) return;
    if ((urlWorkspaceId || urlArtifactId) && !deepLinkApplied.current) return;
    if (urlArtifactId === activeWorkspaceId && !urlWorkspaceId) return;
    navigate(`/${encodeURIComponent(activeWorkspaceId)}`, { replace: true });
  }, [activeWorkspaceId, urlArtifactId, urlWorkspaceId, navigate]);

  // Open a workspace as a tab: dock it when the tabs are an explicit list, then select it.
  const openWorkspaceTab = useCallback((id: string) => {
    if (dockedWorkspaceTabIds && !dockedWorkspaceTabIds.includes(id)) {
      opening.current = id;
      void updatePreferences({
        browser: { ...preferences.browser, dockedWorkspaceCardIds: [...dockedWorkspaceTabIds, id] },
      });
    }
    setActiveWorkspaceId(id);
  }, [dockedWorkspaceTabIds, preferences.browser, updatePreferences]);

  // Deep link: if URL has /:artifactId (or ?workspace=xyz) matching a
  // known workspace, activate it on first load.
  useEffect(() => {
    if (deepLinkApplied.current || workspaces.length === 0) return;
    const targetWsId = urlWorkspaceId || urlArtifactId;
    if (targetWsId) {
      deepLinkApplied.current = true;
      const refuse = () => {
        // A link to a workspace this account cannot reach. Saying so, rather than opening the
        // Inbox as if the link had worked; whether it exists is not revealed either way.
        // 2026-10-13, a tester opened a shared link before being invited and saw their own Inbox.
        toast.error("You can't open this workspace", {
          description: "It hasn't been shared with you, or it no longer exists. Ask its owner for an invitation.",
          duration: 10000,
        });
      };
      if (workspaces.some((w) => w.id === targetWsId)) {
        openWorkspaceTab(targetWsId);
        return;
      }
      // The list may predate the link: an invite claimed in this tab navigates here with the list
      // loaded before the claim. Read it again before refusing. 2026-10-23, a tester claimed a
      // Viewer invite and was told the workspace had not been shared with them.
      // Not a workspace: a link to one artifact (FR-030) opens it in its own window, once it can
      // be read; only a workspace link is opened as a tab.
      listWorkspaces()
        .then(async (fresh) => {
          const list = Array.isArray(fresh) ? fresh : [];
          if (list.some((w) => w.id === targetWsId)) {
            listSeq.current++;
            setWorkspaces(list);
            setListError(null);
            openWorkspaceTab(targetWsId);
            return;
          }
          const linked = await readLinkedArtifact(targetWsId);
          if (!linked) return refuse();
          if (safeParseArtifactContext(linked.context)?.content_type === WORKSPACE_CONTENT_TYPE) {
            const again = await listWorkspaces();
            const fresher = Array.isArray(again) ? again : [];
            if (!fresher.some((w) => w.id === targetWsId)) return refuse();
            listSeq.current++;
            setWorkspaces(fresher);
            setListError(null);
            openWorkspaceTab(targetWsId);
            return;
          }
          openLinkedArtifact(linked);
        })
        .catch(refuse);
    }
  }, [workspaces, urlArtifactId, urlWorkspaceId, openWorkspaceTab]);

  // Create. A failure is toasted here with the server's reason, then rethrown so the
  // caller stops; callers need not toast again.
  const createWorkspace = useCallback(async (
    name: string,
    description: string = '',
    options?: { activate?: boolean }
  ): Promise<Workspace> => {
    let created: Workspace;
    try {
      created = await apiCreateWorkspace({ name, description });
    } catch (err) {
      console.error('Failed to create workspace', err);
      toast.error('Could not create workspace', {
        description: errorDetail(err, err instanceof Error ? err.message : 'Unknown error'),
      });
      throw err;
    }
    listSeq.current++;
    setWorkspaces(prev => [...prev, created]);
    if (dockedWorkspaceTabIds) {
      // Selected while the preference that docks it comes back, as a tab being opened is (BUG-058,
      // 2026-11-10: "New workspace" made it, then the selection fell back to the Inbox).
      opening.current = created.id;
      void updatePreferences({
        browser: { ...preferences.browser, dockedWorkspaceCardIds: [...dockedWorkspaceTabIds, created.id] },
      });
    }
    if (options?.activate !== false) {
      setActiveWorkspaceId(created.id);
    }
    return created;
  }, [dockedWorkspaceTabIds, preferences.browser, updatePreferences]);

  // Update
  const updateWorkspace = useCallback(
    async (updates: Partial<Workspace> & { id: string }) => {
      const { id, name, description } = updates;

      // A rename sets the title the context holds, which is what cards and pickers show, as well
      // as `name`. The whole client context is sent: an update replaces the client's keys.
      const current = workspaces.find(w => w.id === id);
      const payload: WorkspaceUpdate = {
        ...(name !== undefined ? {
          name,
          context: stringifyArtifactContext({ ...safeParseArtifactContext(current?.context), title: name }),
        } : {}),
        ...(description !== undefined ? { description } : {}),
      };

      const updated = await apiUpdateWorkspace(id, payload);
      setWorkspaces(prev => prev.map(w => (w.id === updated.id ? updated : w)));
    },
    [workspaces]
  );

  // Delete
  const deleteWorkspace = useCallback(
    async (id: string) => {
      await trashArtifact(id);
      listSeq.current++;
      setWorkspaces(prev => {
        const remaining = withoutKey(prev, w => w.id, id);
        if (activeWorkspaceId === id) {
          const nextVisible = dockedWorkspaceTabIds
            ? remaining.find((workspace) => dockedWorkspaceTabIds.includes(workspace.id))
            : remaining[0];
          setActiveWorkspaceId(nextVisible?.id || null);
        }
        return remaining;
      });
    },
    [activeWorkspaceId, dockedWorkspaceTabIds]
  );

  const restoreWorkspace = useCallback(async (id: string) => {
    await untrashArtifact(id);
    await readList();
  }, [readList]);

  // Active workspace
  const activeWorkspace = useMemo(
    () => workspaces.find(w => w.id === activeWorkspaceId) || null,
    [workspaces, activeWorkspaceId]
  );

  const value = useMemo<WorkspacesContextType>(
    () => ({
      workspaces,
      activeWorkspace,
      activeWorkspaceId,
      createWorkspace,
      updateWorkspace,
      deleteWorkspace,
      restoreWorkspace,
      setActiveWorkspaceId,
      openWorkspaceTab,
    }),
    [workspaces, activeWorkspace, activeWorkspaceId, createWorkspace, updateWorkspace, deleteWorkspace, restoreWorkspace, openWorkspaceTab]
  );

  return (
    <WorkspacesContext.Provider value={value}>
      {listError !== null && (
        <div
          role="alert"
          className="fixed inset-x-0 top-0 z-50 flex items-center justify-center gap-3 bg-red-50 px-4 py-2 text-sm text-red-800"
        >
          <span>Could not load workspaces: {listError}</span>
          <button
            type="button"
            className="rounded border border-red-300 px-2 py-0.5 font-medium hover:bg-red-100"
            onClick={() => setLoadAttempt(a => a + 1)}
          >
            Retry
          </button>
        </div>
      )}
      {children}
    </WorkspacesContext.Provider>
  );
}
