import { ReactNode, useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { toast } from 'sonner';
import {
  listWorkspaces,
  createWorkspace as apiCreateWorkspace,
  updateWorkspace as apiUpdateWorkspace,
  deleteWorkspace as apiDeleteWorkspace,
} from '../../api/workspaces';
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

export function WorkspacesProvider({ children }: { children: ReactNode }) {
  const { isAuthenticated, loading, user } = useAuth();
  const { preferences, isLoading: preferencesLoading, updatePreferences } = usePreferences();
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [activeWorkspaceId, setActiveWorkspaceId] = useState<string | null>(null);

  const dockedWorkspaceTabIds = useMemo(() => {
    const raw = preferences.browser?.dockedWorkspaceCardIds;
    return Array.isArray(raw) ? raw.map(String).filter(Boolean) : undefined;
  }, [preferences.browser?.dockedWorkspaceCardIds]);

  // Deep link: read artifactId from URL path and workspace from query param.
  const { artifactId: urlArtifactId } = useParams<{ artifactId?: string }>();
  const [searchParams] = useSearchParams();
  const urlWorkspaceId = searchParams.get('workspace');
  const deepLinkApplied = useRef(false);
  // A workspace being opened as a tab before the preference that docks it has come back. The
  // selection below keeps it rather than falling back to a docked tab in the meantime.
  const opening = useRef<string | null>(null);

  // Load workspaces once authenticated
  useEffect(() => {
    if (loading || !isAuthenticated) return;

    listWorkspaces()
      .then(data => {
        setWorkspaces(data);
      })
      .catch(err => {
        console.error('Failed to load workspaces', err);
        toast.error('Could not load workspaces', {
          description: errorDetail(err, err instanceof Error ? err.message : 'Unknown error'),
        });
      });
  }, [isAuthenticated, loading]);

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
      listWorkspaces().then(setWorkspaces).catch(err => console.error('Failed to reload workspaces', err));
    };
    window.addEventListener(ARTIFACT_CHANGED_EVENT, onChange);
    return () => window.removeEventListener(ARTIFACT_CHANGED_EVENT, onChange);
  }, [isAuthenticated, loading]);

  useEffect(() => {
    if (loading || !isAuthenticated || preferencesLoading) return;

    if (workspaces.length === 0) {
      setActiveWorkspaceId(null);
      return;
    }

    const visibleWorkspaces = dockedWorkspaceTabIds
      ? workspaces.filter((workspace) => dockedWorkspaceTabIds.includes(workspace.id))
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
      const inbox = inboxWorkspaceId(visibleWorkspaces, user?.id);
      if (isVisible(inbox)) return inbox;
      return visibleWorkspaces[0]?.id || null;
    });
  }, [dockedWorkspaceTabIds, isAuthenticated, loading, preferencesLoading, workspaces, user?.id, updatePreferences, preferences.browser]);

  useEffect(() => {
    writeLastTab(user?.id, activeWorkspaceId);
  }, [activeWorkspaceId, user?.id]);

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
      listWorkspaces()
        .then((fresh) => {
          const list = Array.isArray(fresh) ? fresh : [];
          if (!list.some((w) => w.id === targetWsId)) return refuse();
          setWorkspaces(list);
          openWorkspaceTab(targetWsId);
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
    setWorkspaces(prev => [...prev, created]);
    if (dockedWorkspaceTabIds) {
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
      await apiDeleteWorkspace(id);
      setWorkspaces(prev => {
        const remaining = prev.filter(w => w.id !== id);
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
      setActiveWorkspaceId,
      openWorkspaceTab,
    }),
    [workspaces, activeWorkspace, activeWorkspaceId, createWorkspace, updateWorkspace, deleteWorkspace, openWorkspaceTab]
  );

  return (
    <WorkspacesContext.Provider value={value}>
      {children}
    </WorkspacesContext.Provider>
  );
}
